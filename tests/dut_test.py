import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ReadOnly, NextTimeStep
from cocotb_bus.drivers import BusDriver
from cocotb.result import TestFailure
from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db
from cocotb_bus.monitors import BusMonitor
import os
import random

test_failures = 0
expected_value = []

def sb_fn(actual_value):
    global expected_value, test_failures
    if not expected_value:
        print("Warning: Unexpected output received")
        return
    expected = expected_value.pop(0)
    print(f"Expected: {expected}, Actual: {actual_value}")
    if actual_value != expected:
        test_failures += 1
        print("  -> Mismatch detected!")

@CoverPoint("top.a", xf=lambda x, y: x, bins=[0, 1])
@CoverPoint("top.b", xf=lambda x, y: y, bins=[0, 1])
@CoverCross("top.cross.ab", items=["top.a", "top.b"])
def ab_cover(a, b):
    pass

@CoverPoint("top.inputport.current_w", xf=lambda x: x.get('current_w'), bins=["Idle_w", "Txn_w"])  # only two states as write_rdy is always 1
@CoverPoint("top.inputport.previous_w", xf=lambda x: x.get('previous_w'), bins=["Idle_w", "Txn_w"])
@CoverCross("top.cross.input", items=["top.inputport.previous_w", "top.inputport.current_w"])
def inputport_cover(Txn_w_dict):
    pass

@CoverPoint("top.outputport.current_r", xf=lambda x: x.get('current_r'), bins=["Idle_r", "Txn_r"])  # only two states as read_rdy is always 1
@CoverPoint("top.outputport.previous_r", xf=lambda x: x.get('previous_r'), bins=["Idle_r", "Txn_r"])
@CoverCross("top.cross.output", items=["top.outputport.previous_r", "top.outputport.current_r"])
def outputport_cover(Txn_r_dict):
    pass

@CoverPoint("top.read_address", xf=lambda x: x, bins=[0, 1, 2, 3])
def read_address_cover(address):
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

    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK, sb_fn)
    InputMonitor(dut, "", dut.CLK, callback=inputport_cover)
    OutputMonitor(dut, "", dut.CLK, callback=outputport_cover)
    # Hit all possible read addresses 0–3 (initial case)
    for addr in range(3):
        read_address_cover(addr)
        await r_drv._driver_sent(addr)
    for i in range(50):  # Random test
        a = random.randint(0, 1)
        b = random.randint(0, 1)
        expected_value.append(a | b)

        await w_drv._driver_sent(4, a)
        await w_drv._driver_sent(5, b)
        ab_cover(a, b)

        # 200 cycles to complete the execution for delayed_dut
        for j in range(200):
            await RisingEdge(dut.CLK)
            await NextTimeStep()

        # Hit all possible read addresses 0–3 (to check in normal working)
        for addr in range(4):
            read_address_cover(addr)
            await r_drv._driver_sent(addr)
    #to set the fifo a full flag
    await w_drv._driver_sent(4, a)
    await w_drv._driver_sent(4, a)
    await w_drv._driver_sent(4, a)
    for addr in range(3):
        read_address_cover(addr)
        await r_drv._driver_sent(addr)
    #to set the fifo b full flag
    await w_drv._driver_sent(5, b)
    await w_drv._driver_sent(5, b)
    await w_drv._driver_sent(5, b)
    for addr in range(3):
        read_address_cover(addr)
        await r_drv._driver_sent(addr)
    # Generate and save coverage report
    coverage_db.report_coverage(cocotb.log.info, bins=True)
    coverage_file = os.path.join(os.getenv("RESULT_PATH", "./"), 'coverage.xml')
    coverage_db.export_to_xml(filename=coverage_file)

    if test_failures > 0:
        raise TestFailure(f"Tests failed: {test_failures}")
    elif expected_value:
        raise TestFailure(f"Test completed but {len(expected_value)} expected values weren't checked")
    print("All test vectors passed successfully!")

class InputDriver(BusDriver):
    _signals = ["write_en", "write_address", "write_data", "write_rdy"]

    def __init__(self, dut, name, clk):
        super().__init__(dut, name, clk)
        self.bus.write_en.value = 0
        self.bus.write_address.value = 0
        self.bus.write_data.value = 0
        self.clk = clk

    async def _driver_sent(self, address, data, sync=True):
        for l in range(random.randint(1, 200)):
            await RisingEdge(self.clk)
        while not self.bus.write_rdy.value:
            await RisingEdge(self.clk)
        self.bus.write_en.value = 1
        self.bus.write_address.value = address
        self.bus.write_data.value = data
        await ReadOnly()
        await RisingEdge(self.clk)
        await NextTimeStep()
        self.bus.write_en.value = 0

class InputMonitor(BusMonitor):
    _signals = ["write_en", "write_address", "write_data", "write_rdy"]

    async def _monitor_recv(self):
        phases_w = {1: "Idle_w", 3: "Txn_w"}  # only two states as write_rdy is always 1
        prev_w = "Idle_w"
        while True:
            await FallingEdge(self.clock)
            await ReadOnly()
            Txn_w = (int(self.bus.write_en.value) << 1) | int(self.bus.write_rdy.value)
            state_w = phases_w.get(Txn_w)
            if state_w:
                inputport_cover({'previous_w': prev_w, 'current_w': state_w})
                prev_w = state_w

class OutputDriver(BusDriver):
    _signals = ["read_en", "read_address", "read_data", "read_rdy"]

    def __init__(self, dut, name, clk, sb_callback):
        super().__init__(dut, name, clk)
        self.bus.read_en.value = 0
        self.bus.read_address.value = 0
        self.clk = clk
        self.callback = sb_callback

    async def _driver_sent(self, address, sync=True):
        for k in range(random.randint(1, 200)):
            await RisingEdge(self.clk)
        while not self.bus.read_rdy.value:
            await RisingEdge(self.clk)
        self.bus.read_en.value = 1
        self.bus.read_address.value = address
        await ReadOnly()

        # Only check scoreboard for y_output (address 3)
        if self.callback and address == 3:
            self.callback(int(self.bus.read_data.value))
        elif address in [0, 1, 2]:
            cocotb.log.info(f"address={address}, value={int(self.bus.read_data.value)}")

        await RisingEdge(self.clk)
        await NextTimeStep()
        self.bus.read_en.value = 0

class OutputMonitor(BusMonitor):
    _signals = ["read_en", "read_address", "read_data", "read_rdy"]

    async def _monitor_recv(self):
        phases_r = {1: "Idle_r", 3: "Txn_r"}  # only two states as read_rdy is always 1
        prev_r = "Idle_r"
        while True:
            await FallingEdge(self.clock)
            await ReadOnly()
            Txn_r = (int(self.bus.read_en.value) << 1) | int(self.bus.read_rdy.value)
            state_r = phases_r.get(Txn_r)
            if state_r:
                outputport_cover({'previous_r': prev_r, 'current_r': state_r})
                prev_r = state_r
