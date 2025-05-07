import cocotb
from cocotb.triggers import Timer, RisingEdge, ReadOnly, NextTimeStep
from cocotb_bus.drivers import BusDriver

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

@cocotb.test()
async def dut_test(dut):
    global expected_value, test_failures
    test_failures = 0
    
    # Test vectors (a, b, expected OR result)
    # Add edge cases to your test vectors
    a = (0, 0, 1, 1)
    b = (0, 1, 0, 1)
    expected_value = [0, 1, 1, 1]
    
    # Reset sequence (2 cycles)
    dut.RST_N.value = 0
    await Timer(20, 'ns')
    dut.RST_N.value = 1
    await Timer(20, 'ns')

    # Create drivers
    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK, sb_fn)

    for i in range(4):
        # Write phase (2 cycles - accounts for b_ff size=1)
        await w_drv._driver_sent(4, a[i])  # Write to a_ff
        await w_drv._driver_sent(5, b[i])  # Write to b_ff
        
        # Processing delay (3 cycles - accounts for a_ff and y_ff size=2)
        for _ in range(200):
            await RisingEdge(dut.CLK)
            await NextTimeStep()
        
        # Read phase (1 cycle)
        await r_drv._driver_sent(3)  # Read from y_ff

    # Final check
    assert test_failures == 0, f"Test failed with {test_failures} mismatches"
    assert not expected_value, f"Test completed but {len(expected_value)} expected values weren't checked"
    
    print("All test vectors passed successfully!")

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
        if self.callback:
            self.callback(int(self.bus.read_data.value))
        
        await RisingEdge(self.clk)
        self.bus.read_en.value = 0
        await NextTimeStep()
