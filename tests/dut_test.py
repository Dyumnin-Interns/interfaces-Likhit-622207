import cocotb
from cocotb.triggers import Timer,RisingEdge, ReadOnly, NextTimeStep
from cocotb_bus.drivers import BusDriver

def cb_fn(actual_value):
    global expected_value
    assert actual_value == expected_value.pop(0), f"Unexpected output: got {actual_value}"


@cocotb.test()
async def dut_test(dut):
    global expected_value
    a = (0, 0, 1, 1)
    b = (0, 1, 0, 1)
    expected_value = [0, 1, 1, 0]
    dut.RST_N.value=0
    await Timer(1,'ns')
    dut.RST_N.value = 1
    await Timer(1,'ns')
    await RisingEdge(dut.CLK)
    dut.RST_N.value = 0
    w_drv = InputDriver(dut, "write_bus", dut.CLK)
    r_drv = OutputDriver(dut, "read_bus", dut.CLK, cb_fn)
    for i in range(4):
        # enqueue a
        await w_drv.append(4, a[i])
        #await RisingEdge(dut.CLK)
        # enqueue b
        await w_drv.append(5, b[i])
        #await RisingEdge(dut.CLK)
    while len(expected_value)>0:
         await Timer(2,'ns')
    #while expected_value:
    #    await Timer(2, 'ns')

class InputDriver(BusDriver):
    _signals=["write_en", "write_address", "write_data", "write_rdy"]

    def __init__(self,dut,name,clk):
        BusDriver.__init__(self,dut,name,clk)
        self.bus.write_en.value=0
        self.bus.write_address.value=0
        self.bus.write_data.value=0
        self.clk=clk

    async def _driver_sent(self,address,data,sync=True):
        if self.bus.write_rdy.value != 1:
           await RisingEdge(self.bus.write_rdy)
        self.bus.write_en.value=1
        self.bus.write_address.value = address
        self.bus.write_data.value=data
        await ReadOnly()
        await RisingEdge(self.clk)
        self.bus.write_en.value=0

class OutputDriver(BusDriver):
    _signals=["read_en", "read_address", "read_data", "read_rdy"]

    def __init__(self,dut,name,clk,cb_callback):
        BusDriver.__init__(self,dut,name,clk)
        self.bus.read_en.value=0
        self.bus.read_address.value=0
        self.clk=clk
        self.callback=cb_callback
        self.append(0)

    async def _driver_sent(self,address,data,sync=True):
        while True:
            if self.bus.read_rdy.value != 1:
               await RisingEdge(self.bus.read_rdy)
            self.bus.read_en.value=1
            self.bus.read_address.value = address
            #self.bus.readdata=data
            await ReadOnly()
            self.callback(self.bus.read_data.value)
            await RisingEdge(self.clk)
            self.bus.read_en.value=0
            await NextTimeStep()
            #cocotb.start_soon(r_drv._driver_sent(4, 0))  # 4 = read_address
