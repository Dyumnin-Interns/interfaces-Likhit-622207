module dut_wrap(
    output reg CLK,
    input RST_N,

    // action method write
    input [2:0] write_address,
    input write_data,
    input write_en,
    output write_rdy,

    // actionvalue method read
    input [2:0] read_address,
    input read_en,
    output read_data,
    output read_rdy
    // to expose FIFO flags
    output            a_full_n,
    output            b_full_n,
    output            y_empty_n
);
    
    // Instantiate DUT
    dut dut_inst (
        .CLK(CLK),
        .RST_N(RST_N),
        .write_address(write_address),
        .write_data(write_data),
        .write_en(write_en),
        .write_rdy(write_rdy),
        .read_address(read_address),
        .read_data(read_data),
        .read_en(read_en),
        .read_rdy(read_rdy)
    );

    assign a_full_n  = dut_inst.a_ff$FULL_N;
    assign b_full_n  = dut_inst.b_ff$FULL_N;
    assign y_empty_n = dut_inst.y_ff$EMPTY_N;
    
    // Clock generation with proper delay
    initial begin
        $dumpfile("waves_dut.vcd");
        $dumpvars(0, dut_wrap);
        CLK = 0;
        forever begin
            #5 CLK = ~CLK; // 10ns clock period
        end
    end

endmodule
