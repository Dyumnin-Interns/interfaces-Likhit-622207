import cocotb
from cocotb.triggers import Timer, RisingEdge, ReadOnly, NextTimeStep
from cocotb_bus.drivers import BusDriver

@cocotb.test()
async def dut_test(dut):
    expected_value = [0, 1, 1, 1]
    test_failures = 0

    def sb_fn(actual_value):
        nonlocal expected_value, test_failures
        if not expected_value:
            dut._log.warning("Unexpected output received")
            return
        
        expected = expected_value.pop(0)
        dut._log.info(f"Expected: {expected}, Actual: {actual_value}")
        
        if actual_value != expected:
            test_failures += 1
            dut._log.error("  -> Mismatch detected!")

    # Reset sequence
    dut.RST_N.value = 0
    await RisingEdge(dut.CLK)
    dut.RST_N.value = 1
    await RisingEdge(dut.CLK)

    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK, sb_fn)
    
    a = (0, 0, 1, 1)
    b = (0, 1, 0, 1)

    for i in range(4):
        await w_drv._driver_sent(4, a[i])
        await w_drv._driver_sent(5, b[i])
        
        for _ in range(3):
            await RisingEdge(dut.CLK)
            await NextTimeStep()

        await r_drv._driver_sent(3)
        await RisingEdge(dut.CLK)
        await NextTimeStep()

    if test_failures > 0:
        raise TestFailure(f"Test failed with {test_failures} mismatches")
    elif expected_value:
        raise TestFailure(f"{len(expected_value)} expected values were not checked")
    
    dut._log.info("All test vectors passed successfully!")

class InputDriver(BusDriver):
    _signals = ["write_en", "write_address", "write_data", "write_rdy"]

    def __init__(self, dut, name, clk):
        BusDriver.__init__(self, dut, name, clk)
        self.bus.write_en.value = 0
        self.bus.write_address.value = 0
        self.bus.write_data.value = 0
        self.clk = clk

    async def _driver_sent(self, address, data, sync=True):
        await RisingEdge(self.clk)
        while not self.bus.write_rdy.value:
            await RisingEdge(self.clk)
        
        self.bus.write_en.value = 1
        self.bus.write_address.value = address
        self.bus.write_data.value = data
        
        await ReadOnly()
        await RisingEdge(self.clk)
        self.bus.write_en.value = 0
        await NextTimeStep()

class OutputDriver(BusDriver):
    _signals = ["read_en", "read_address", "read_data", "read_rdy"]

    def __init__(self, dut, name, clk, sb_callback):
        BusDriver.__init__(self, dut, name, clk)
        self.bus.read_en.value = 0
        self.bus.read_address.value = 0
        self.clk = clk
        self.callback = sb_callback

    async def _driver_sent(self, address, sync=True):
        await RisingEdge(self.clk)
        while not self.bus.read_rdy.value:
            await RisingEdge(self.clk)        
        self.bus.read_en.value = 1
        self.bus.read_address.value = address
        
        await ReadOnly()
        self.callback(int(self.bus.read_data.value))
        
        await RisingEdge(self.clk)
        self.bus.read_en.value = 0
        await NextTimeStep()
