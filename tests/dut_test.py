import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ReadOnly, NextTimeStep, Event
from cocotb_bus.drivers import BusDriver
from cocotb.result import TestFailure
from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db
from cocotb_bus.monitors import BusMonitor
import os
import random
import asyncio

test_failures = 0
expected_value = []

def sb_fn(actual_value):
    global expected_value, test_failures
    if not expected_value:
        cocotb.log.warning("Unexpected output received")
        return
    expected = expected_value.pop(0)
    cocotb.log.info(f"Expected: {expected}, Actual: {actual_value}")
    if actual_value != expected:
        test_failures += 1
        cocotb.log.error("  -> Mismatch detected!")

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
    global expected_value, test_failures
    test_failures = 0
    expected_value = []

    dut.RST_N.value = 1
    await Timer(50, 'ns')
    dut.RST_N.value = 0
    await Timer(50, 'ns')
    dut.RST_N.value = 1
    await RisingEdge(dut.CLK)

    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK, sb_fn)
    InputMonitor(dut, "", dut.CLK, callback=inputport_cover)
    OutputMonitor(dut, "", dut.CLK, callback=outputport_cover)

    lock = False

    async def acquire_lock():
        nonlocal lock
        while lock:
            await Timer(1, 'ns')
        lock = True

    def release_lock():
        nonlocal lock
        lock = False

    # Initial reads (addresses 0–2)
    for addr in range(3):
        read_address_cover(addr)
        await r_drv._driver_sent(addr)

    # Storage for a, b, and expected y
    a_list = []
    b_list = []
    NUM_VECTORS = 50

    # Thread: drive ‘a’ into address 4
    async def drive_a():
        for _ in range(NUM_VECTORS):
            a = random.randint(0, 1)
            a_list.append(a)
            while int(dut.a_full_n.value) != 1:
                await RisingEdge(dut.CLK)
            await acquire_lock()
            await w_drv._driver_sent(4, a)
            release_lock()
            await RisingEdge(dut.CLK)
            await Timer(random.randint(1, 100), units='ns')

    # Thread: drive ‘b’ into address 5
    async def drive_b():
        for _ in range(NUM_VECTORS):
            b = random.randint(0, 1)
            b_list.append(b)
            while int(dut.b_full_n.value) != 1:
                await RisingEdge(dut.CLK)
            await acquire_lock()
            await w_drv._driver_sent(5, b)
            release_lock()
            await RisingEdge(dut.CLK)
            await Timer(random.randint(1, 100), units='ns')


    # Thread: read back y = a | b from address 3
    async def read_y():
        # wait until both lists have data before sampling each index
        for idx in range(NUM_VECTORS):
            retries = 0
            while idx >= len(a_list) or idx >= len(b_list):
                if retries > 1000:
                    raise TestFailure("Timeout")
                await Timer(10, 'ns')
                retries += 1
            ab_cover(a_list[idx], b_list[idx])
            read_address_cover(3)
            expected_value.append(a_list[idx] | b_list[idx])
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

    coverage_db.report_coverage(cocotb.log.info, bins=True)
    coverage_file = os.path.join(os.getenv("RESULT_PATH", "./"), 'coverage.xml')
    coverage_db.export_to_xml(filename=coverage_file)

    if test_failures > 0:
        raise TestFailure(f"{test_failures} mismatches")
    elif expected_value:
        raise TestFailure(f"{len(expected_value)} expected not checked")
    cocotb.log.info("All test vectors passed!")


# DRIVER + MONITOR CLASSES
class InputDriver(BusDriver):
    _signals = ["write_en", "write_address", "write_data"]

    def __init__(self, dut, name, clk):
        BusDriver.__init__(self, dut, name, clk)
        self.bus.write_en.value = 0
        self.bus.write_address.value = 0
        self.bus.write_data.value = 0
        self.clk = clk
        self.a_full_n = dut.a_full_n
        self.b_full_n = dut.b_full_n

    async def _driver_sent(self, address, data, sync=True):
        for l in range(random.randint(1,10)):
            await RisingEdge(self.clk)
        fifo_flag = self.a_full_n if address == 4 else self.b_full_n
        while int(fifo_flag.value) != 1:
            await RisingEdge(self.clk)
        self.bus.write_address.value = address
        self.bus.write_data.value = data
        self.bus.write_en.value = 1
        await ReadOnly()
        await RisingEdge(self.clk)
        await NextTimeStep()
        self.bus.write_en.value = 0

class InputMonitor(BusMonitor):
    _signals = ["write_en", "write_address", "write_data"]

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
            full_flag = self.a_full_n if int(self.bus.write_address.value) == 4 else self.b_full_n
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
        self.y_empty_n              = dut.y_empty_n

    async def _driver_sent(self, address, sync=True):
        for _ in range(random.randint(1, 10)):
            await RisingEdge(self.clk)
        if address == 3:
            while int(self.y_empty_n.value) != 1:
                await RisingEdge(self.clk)
        self.bus.read_address.value = address
        self.bus.read_en.value      = 1
        await ReadOnly()
        if address == 3:
            self.callback(int(self.bus.read_data.value))
        else:
            cocotb.log.info(f"ADDR={address} DATA={int(self.bus.read_data.value)}")
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
