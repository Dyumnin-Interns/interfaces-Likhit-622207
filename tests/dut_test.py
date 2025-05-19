import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ReadOnly, NextTimeStep, Lock
from cocotb_bus.drivers import BusDriver
from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db
from cocotb_bus.monitors import BusMonitor
import os
import random

def sb_fn(actual_value):
    if not expected_value:
        cocotb.log.warning("Unexpected output")
        return
    expected = expected_value.pop(0)
    assert actual_value == expected, "Mismatch"
    cocotb.log.info(f"Expected: {expected}, Actual: {actual_value}")

@CoverPoint("top.a", xf=lambda a, b: a, bins=[0, 1])
@CoverPoint("top.b", xf=lambda a, b: b, bins=[0, 1])
@CoverCross("top.cross.ab", items=["top.a", "top.b"])
def ab_cover(a, b):
    pass

@CoverPoint("top.input.current",
            xf=lambda t: t.get('current_w'),
            bins=["RDY_w", "Idle_w", "Stall_w", "Txn_w"])
@CoverPoint("top.input.previous",
            xf=lambda t: t.get('previous_w'),
            bins=["RDY_w", "Idle_w", "Stall_w", "Txn_w"])
@CoverCross("top.cross.input", items=["top.input.previous", "top.input.current"])
def inputport_cover(t):
    pass

@CoverPoint("top.output.current",
            xf=lambda t: t.get('current_r'),
            bins=["Idle_r", "RDY_r", "Stall_r", "Txn_r"])
@CoverPoint("top.output.previous",
            xf=lambda t: t.get('previous_r'),
            bins=["Idle_r", "RDY_r", "Stall_r", "Txn_r"])
@CoverCross("top.cross.output", items=["top.output.previous", "top.output.current"])
def outputport_cover(t):
    pass

@CoverPoint("top.read_address", xf=lambda a: a, bins=[0, 1, 2, 3])
def read_address_cover(a):
    pass


@cocotb.test()
async def dut_test(dut):
    global expected_value
    expected_value = []

    dut.RST_N.value = 1
    await Timer(50, 'ns')
    dut.RST_N.value = 0
    await Timer(50, 'ns')
    dut.RST_N.value = 1
    await RisingEdge(dut.CLK)

    input_lock = cocotb.triggers.Lock()
    output_lock= cocotb.triggers.Lock()

    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK,sb_fn)
    InputMonitor(dut, "", dut.CLK, callback=inputport_cover)
    OutputMonitor(dut, "", dut.CLK, callback=outputport_cover)

    # Initial reads (addresses 0–2)
    for addr in range(3):
        read_address_cover(addr)
        await r_drv._driver_sent(addr)

    # Storage for a, b, and expected y
    a_list = []
    b_list = []
    NUM_VECTORS = 50

    # drive ‘a’ into address 4
    async def drive_a():
        for _ in range(NUM_VECTORS):
            a = random.randint(0, 1)
            a_list.append(a)
            retries = 0
            async with output_lock:
                read_address_cover(0)
                await r_drv._driver_sent(0)
                while int(dut.read_data.value) != 1:#a_full_n
                    await RisingEdge(dut.CLK)#dut.read_data
                    assert (retries < 1000),"Timeout_a"
                    retries += 1
            async with input_lock:
                await w_drv._driver_sent(4, a)
            await RisingEdge(dut.CLK)
            await Timer(random.randint(1, 100), units='ns')

    # drive ‘b’ into address 5
    async def drive_b():
        for _ in range(NUM_VECTORS):
            b = random.randint(0, 1)
            b_list.append(b)
            retries = 0
            async with output_lock:
                read_address_cover(1)
                await r_drv._driver_sent(1)
                while int(dut.read_data.value) != 1:#b_full_n
                    await RisingEdge(dut.CLK) #dut.read_data
                    assert (retries < 1000),"Timeout_b"
                    retries += 1
            async with input_lock:
                await w_drv._driver_sent(5, b)
            await RisingEdge(dut.CLK)
            await Timer(random.randint(1, 100), units='ns')


    # read back y = a | b from address 3
    async def read_y():
        # wait until both lists have data before sampling each index
        for idx in range(NUM_VECTORS):
            retries = 0
            while idx >= len(a_list) or idx >= len(b_list):
                assert (retries < 1000),"Timeout_y"
                await Timer(10, 'ns')
                retries += 1
            ab_cover(a_list[idx], b_list[idx])
            expected_value.append(a_list[idx] | b_list[idx])
            retries = 0
            async with output_lock:
                read_address_cover(2)
                await r_drv._driver_sent(2)
                while int(dut.read_data.value) != 1:#y_empty_n
                    await RisingEdge(dut.CLK)
                    assert (retries < 1000),"y_flag stuck at 0"
                    retries += 1
                await RisingEdge(dut.CLK)         
                read_address_cover(3)
                await r_drv._driver_sent(3)
                # Initial reads (addresses 0–2)
                for addr in range(3):
                    read_address_cover(addr)
                    await r_drv._driver_sent(addr)
            await RisingEdge(dut.CLK)
            await Timer(random.randint(1,100), units='ns')

    # Launch all three threads
    task_a = cocotb.start_soon(drive_a())
    task_b = cocotb.start_soon(drive_b())
    task_r = cocotb.start_soon(read_y())

    await task_a
    await task_b
    await task_r
        
    # fill b fifo (depth=1)
    await w_drv._driver_sent(5, 0)
    retries = 0
    # Read b flag
    read_address_cover(1)
    await r_drv._driver_sent(1)
    while True:
        if int(dut.read_data.value) == 0:
            cocotb.log.info("b_full_n goes to zero")
            break
        assert (retries < 1000), "b_full_n flag stuck at 1"
        await RisingEdge(dut.CLK)
        retries += 1
    # empty b fifo
    await w_drv._driver_sent(4, 1)#drive 1 to a
    expected_value.append(1)
    read_address_cover(2)
    await r_drv._driver_sent(2)
    while int(dut.read_data.value) != 1:#y_empty_n
        await RisingEdge(dut.CLK)
    read_address_cover(3)
    await r_drv._driver_sent(3)#collect y
    # fill a fifo (depth=2)
    await w_drv._driver_sent(4, 0)#drive 0 to a
    await w_drv._driver_sent(4, 1)#drive 1 to a
    retries = 0
    # Read a flag
    read_address_cover(0)
    await r_drv._driver_sent(0)
    while True:
        if int(dut.read_data.value) == 0:
            cocotb.log.info("a_full_n goes to zero")
            break
        assert (retries < 1000), "a_full_n flag stuck at 1"
        await RisingEdge(dut.CLK)
        retries += 1
    #empty y fifo (depth=2)
    await w_drv._driver_sent(5, 0)#drive 0 to b
    expected_value.append(0)
    read_address_cover(2)
    await r_drv._driver_sent(2)
    while int(dut.read_data.value) != 1:#y_empty_n
        await RisingEdge(dut.CLK)
    read_address_cover(3)
    await r_drv._driver_sent(3)#collect y(1st time)
    await w_drv._driver_sent(5, 0)#drive 0 to b
    expected_value.append(1)
    read_address_cover(2)
    await r_drv._driver_sent(2)
    while int(dut.read_data.value) != 1:#y_empty_n
        await RisingEdge(dut.CLK)
    read_address_cover(3)
    await r_drv._driver_sent(3)#collect y(2nd time)
    retries = 0
    # Read y flag
    read_address_cover(2)
    await r_drv._driver_sent(2)
    while True:
        if int(dut.read_data.value) == 0:
            cocotb.log.info("y_empty_n goes to zero")
            break
        assert (retries < 1000), "y_empty_n flag stuck at 1"
        await RisingEdge(dut.CLK)
        retries += 1
    coverage_db.report_coverage(cocotb.log.info, bins=True)
    coverage_file = os.path.join(os.getenv("RESULT_PATH", "./"), 'coverage.xml')
    coverage_db.export_to_xml(filename=coverage_file)

# DRIVER + MONITOR CLASSES
class InputDriver(BusDriver):
    _signals = ["write_en", "write_address", "write_data", "read_en", "read_address", "read_data"]

    def __init__(self, dut, name, clk):
        BusDriver.__init__(self, dut, name, clk)
        self.bus.write_en.value = 0
        self.bus.write_address.value = 0
        self.bus.write_data.value = 0
        self.clk = clk
        self.a_full_n = dut.a_full_n
        self.b_full_n = dut.b_full_n

    async def _driver_sent(self, address, data, sync=True):
        for l in range(random.randint(1,20)):
            await RisingEdge(self.clk)
        #if address == 4:
        #    self.bus.read_address.value = 0
        #else:
        #    self.bus.read_address.value = 1
        #while int(self.bus.read_data.value) != 1:
        #    await RisingEdge(self.clk)
        self.bus.write_address.value = address
        self.bus.write_data.value = data
        self.bus.write_en.value = 1
        await ReadOnly()
        await RisingEdge(self.clk)
        await NextTimeStep()
        self.bus.write_en.value = 0

class InputMonitor(BusMonitor):
    _signals = ["write_en", "write_address", "write_data", "read_en", "read_address", "read_data"]

    def __init__(self, dut, name, clock, callback):
        BusMonitor.__init__(self, dut, name, clock, callback)
        self.a_full_n = dut.a_full_n
        self.b_full_n = dut.b_full_n

    async def _monitor_recv(self):
        prev_w = "Idle"
        phases_w = {0: "RDY_w",    # Can write, not trying to write
                    1: " Idle_w",  # FIFO full, not writing
                    2: "Stall_w",  # Trying to write, but FIFO full
                    3: "Txn_w"     # Active transaction, write enabled and FIFO ready
        }    
        while True:
            await FallingEdge(self.clock)
            await ReadOnly()
            if int(self.bus.write_address.value) == 4:
                full_flag = self.a_full_n             
            else:
                full_flag = self.b_full_n
            curr_w = (int(self.bus.write_en.value) << 1) | int(full_flag.value)
            inputport_cover({'previous_w': prev_w, 'current_w': phases_w[curr_w]})
            prev_w = phases_w[curr_w]

class OutputDriver(BusDriver):
    _signals = ["read_en", "read_address", "read_data"]

    def __init__(self, dut, name, clk, sb_callback):
        BusDriver.__init__(self, dut, name, clk)
        self.bus.read_en.value      = 0
        self.bus.read_address.value = 0
        self.clk                    = clk
        self.callback               = sb_callback

    async def _driver_sent(self, address, sync=True):
        for _ in range(random.randint(1, 20)):
            await RisingEdge(self.clk)
        #if address == 3:
        #    while int(self.y_empty_n.value) != 1:
        #        await RisingEdge(self.clk)
        self.bus.read_address.value = address
        self.bus.read_en.value      = 1
        await ReadOnly()
        cocotb.log.info(f"ADDR={address} DATA={int(self.bus.read_data.value)}")
        if address == 3:
            self.callback(int(self.bus.read_data.value))
        await RisingEdge(self.clk)
        await NextTimeStep()
        self.bus.read_en.value = 0

class OutputMonitor(BusMonitor):
    _signals = ["read_en", "read_address", "read_data"]

    def __init__(self, dut, name, clock, callback):
        BusMonitor.__init__(self, dut, name, clock, callback)
        self.y_empty_n = dut.y_empty_n

    async def _monitor_recv(self):
        prev_r = "Idle"
        phases_r = {0: "Idle_r",  # Not reading, no data
                    1: "RDY_r",   # Data available, not reading
                    2: "Correct", # Trying to read, but FIFO empty
                    3: "Txn_r"    # Successful read transaction
        }
        while True:
            await FallingEdge(self.clock)
            await ReadOnly()
            curr_r = (int(self.bus.read_en.value) << 1) | int(self.y_empty_n.value)
            outputport_cover({'previous_r': prev_r, 'current_r': phases_r[curr_r]})
            prev_r = phases_r[curr_r]
