import cocotb
from cocotb.triggers import Timer, RisingEdge, ReadOnly, NextTimeStep
from cocotb_bus.drivers import BusDriver

def get_sb_fn(expected_values, test_failures_ref):
    def sb_fn(actual_value):
        if not expected_values:
            print("Warning: Unexpected output received")
            return

        expected = expected_values.pop(0)
        print(f"Expected: {expected}, Actual: {actual_value}")

        if actual_value != expected:
            test_failures_ref[0] += 1
            print("  -> Mismatch detected!")
    return sb_fn


@cocotb.test()
async def dut_test(dut):
    global expected_value, test_failures
    test_failures = 0
    
    # Test vectors (a, b, expected OR result)
    a = (0, 0, 1, 1)
    b = (0, 1, 0, 1)
    expected_value = [0, 1, 1, 1]

    # Extended reset sequence for delayed DUT
    dut.RST_N.value = 0
    await Timer(100, 'ns')  # Longer reset for delayed version
    dut.RST_N.value = 1
    await Timer(100, 'ns')  # Additional stabilization

    # Create drivers
    w_drv = InputDriver(dut, "", dut.CLK)
    r_drv = OutputDriver(dut, "", dut.CLK, sb_fn)

    for i in range(4):
        # Write phase with handshaking
        await w_drv._driver_sent(4, a[i])  # Write to a_ff
        await w_drv._driver_sent(5, b[i])  # Write to b_ff
        
        # Extended processing delay for delayed DUT (7 cycles)
        for _ in range(3):
            await RisingEdge(dut.CLK)
            await NextTimeStep()
        
        # Read phase
        await r_drv._driver_sent(3)  # Read from y_ff
        await RisingEdge(dut.CLK)
        await NextTimeStep()

        # Additional recovery cycle
        await RisingEdge(dut.CLK)
        await NextTimeStep()

    # Final check
    if test_failures > 0:
        assert False, f"Test failed with {test_failures} mismatches"
    elif expected_value:
        assert False, f"Test completed but {len(expected_value)} expected values weren't checked"
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
        self.callback(int(self.bus.read_data.value))
        
        await RisingEdge(self.clk)
        self.bus.read_en.value = 0
        await NextTimeStep()
