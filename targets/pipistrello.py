from fractions import Fraction

from migen.fhdl.std import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoclib.mem import sdram
from misoclib.mem.sdram.phy import s6ddrphy
from misoclib.mem.flash import spiflash
from misoclib.soc.sdram import SDRAMSoC

class _CRG(Module):
	def __init__(self, platform, clk_freq):
		self.clock_domains.cd_sys = ClockDomain()
		self.clock_domains.cd_sdram_half = ClockDomain()
		self.clock_domains.cd_sdram_full_wr = ClockDomain()
		self.clock_domains.cd_sdram_full_rd = ClockDomain()

		self.clk4x_wr_strb = Signal()
		self.clk4x_rd_strb = Signal()

		f0 = 50*1000*1000
		clk50 = platform.request("clk50")
		clk50a = Signal()
		self.specials += Instance("IBUFG", i_I=clk50, o_O=clk50a)
		clk50b = Signal()
		self.specials += Instance("BUFIO2", p_DIVIDE=1,
			p_DIVIDE_BYPASS="TRUE", p_I_INVERT="FALSE",
			i_I=clk50a, o_DIVCLK=clk50b)
		f = Fraction(int(clk_freq), int(f0))
		n, m = f.denominator, f.numerator
		assert f0/n*m == clk_freq
		p = 8
		pll_lckd = Signal()
		pll_fb = Signal()
		pll = Signal(6)
		self.specials.pll = Instance("PLL_ADV", p_SIM_DEVICE="SPARTAN6",
			p_BANDWIDTH="OPTIMIZED", p_COMPENSATION="INTERNAL",
			p_REF_JITTER=.01, p_CLK_FEEDBACK="CLKFBOUT",
			i_DADDR=0, i_DCLK=0, i_DEN=0, i_DI=0, i_DWE=0, i_RST=0, i_REL=0,
			p_DIVCLK_DIVIDE=1, p_CLKFBOUT_MULT=m*p//n, p_CLKFBOUT_PHASE=0.,
			i_CLKIN1=clk50b, i_CLKIN2=0, i_CLKINSEL=1,
			p_CLKIN1_PERIOD=1/f0, p_CLKIN2_PERIOD=0.,
			i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb, o_LOCKED=pll_lckd,
			o_CLKOUT0=pll[0], p_CLKOUT0_DUTY_CYCLE=.5,
			o_CLKOUT1=pll[1], p_CLKOUT1_DUTY_CYCLE=.5,
			o_CLKOUT2=pll[2], p_CLKOUT2_DUTY_CYCLE=.5,
			o_CLKOUT3=pll[3], p_CLKOUT3_DUTY_CYCLE=.5,
			o_CLKOUT4=pll[4], p_CLKOUT4_DUTY_CYCLE=.5,
			o_CLKOUT5=pll[5], p_CLKOUT5_DUTY_CYCLE=.5,
			p_CLKOUT0_PHASE=0., p_CLKOUT0_DIVIDE=p//4, # sdram wr rd
			p_CLKOUT1_PHASE=0., p_CLKOUT1_DIVIDE=p//8,
			p_CLKOUT2_PHASE=270., p_CLKOUT2_DIVIDE=p//2, # sdram dqs adr ctrl
			p_CLKOUT3_PHASE=250., p_CLKOUT3_DIVIDE=p//2, # off-chip ddr
			p_CLKOUT4_PHASE=0., p_CLKOUT4_DIVIDE=p//1,
			p_CLKOUT5_PHASE=0., p_CLKOUT5_DIVIDE=p//1, # sys
		)
		self.specials += Instance("BUFG", i_I=pll[5], o_O=self.cd_sys.clk)
		self.specials += AsyncResetSynchronizer(self.cd_sys, ~pll_lckd)
		self.specials += Instance("BUFG", i_I=pll[2], o_O=self.cd_sdram_half.clk)
		self.specials += Instance("BUFPLL", p_DIVIDE=4,
							i_PLLIN=pll[0], i_GCLK=self.cd_sys.clk,
							i_LOCKED=pll_lckd, o_IOCLK=self.cd_sdram_full_wr.clk,
							o_SERDESSTROBE=self.clk4x_wr_strb)
		self.comb += [
			self.cd_sdram_full_rd.clk.eq(self.cd_sdram_full_wr.clk),
			self.clk4x_rd_strb.eq(self.clk4x_wr_strb),
		]
		clk_sdram_half_shifted = Signal()
		self.specials += Instance("BUFG", i_I=pll[3], o_O=clk_sdram_half_shifted)
		clk = platform.request("sdram_clock")
		self.specials += Instance("ODDR2", p_DDR_ALIGNMENT="NONE",
			p_INIT=0, p_SRTYPE="SYNC",
			i_D0=1, i_D1=0, i_S=0, i_R=0, i_CE=1,
			i_C0=clk_sdram_half_shifted, i_C1=~clk_sdram_half_shifted,
			o_Q=clk.p)
		self.specials += Instance("ODDR2", p_DDR_ALIGNMENT="NONE",
			p_INIT=0, p_SRTYPE="SYNC",
			i_D0=0, i_D1=1, i_S=0, i_R=0, i_CE=1,
			i_C0=clk_sdram_half_shifted, i_C1=~clk_sdram_half_shifted,
			o_Q=clk.n)

class BaseSoC(SDRAMSoC):
	default_platform = "pipistrello"

	csr_map = {
		"spiflash":	16,
	}
	csr_map.update(SDRAMSoC.csr_map)

	def __init__(self, platform, **kwargs):
		clk_freq = 75*1000*1000
		if not kwargs.get("with_rom"):
			kwargs["rom_size"] = 0x1000000 # 128 Mb
		SDRAMSoC.__init__(self, platform, clk_freq,
					cpu_reset_address=0x170000, **kwargs) # 1.5 MB

		self.submodules.crg = _CRG(platform, clk_freq)

		if not self.with_sdram:
			sdram_geom = sdram.GeomSettings(
				bank_a=2,
				row_a=13,
				col_a=10
			)
			sdram_timing = sdram.TimingSettings(
				tRP=self.ns(15),
				tRCD=self.ns(15),
				tWR=self.ns(15),
				tWTR=2,
				tREFI=self.ns(64*1000*1000/8192, False),
				tRFC=self.ns(72),
				req_queue_size=8,
				read_time=32,
				write_time=16
			)
			self.submodules.ddrphy = s6ddrphy.S6DDRPHY(platform.request("sdram"),
				"LPDDR", rd_bitslip=1, wr_bitslip=3, dqs_ddr_alignment="C1")
			self.comb += [
				self.ddrphy.clk4x_wr_strb.eq(self.crg.clk4x_wr_strb),
				self.ddrphy.clk4x_rd_strb.eq(self.crg.clk4x_rd_strb),
			]
			platform.add_platform_command("""
	PIN "BUFG.O" CLOCK_DEDICATED_ROUTE = FALSE;
	""")
			self.register_sdram_phy(self.ddrphy, sdram_geom, sdram_timing)

		self.submodules.spiflash = spiflash.SpiFlash(platform.request("spiflash4x"), dummy=11, div=2)
		self.flash_boot_address = 0x180000

		# If not in ROM, BIOS is in SPI flash
		if not self.with_rom:
			self.register_rom(self.spiflash.bus)

default_subtarget = BaseSoC
