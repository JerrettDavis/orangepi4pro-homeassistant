/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright(c) 2020 - 2023 Allwinner Technology Co.,Ltd. All rights reserved. */
/*
 * A V4L2 driver for OV5647 Raw cameras.
 *
 * Copyright (c) 2018 by Allwinnertech Co., Ltd.  http://www.allwinnertech.com
 *
 * Authors:  Zheng ZeQun <zequnzheng@allwinnertech.com>
 *    Liang WeiJie <liangweijie@allwinnertech.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 */
#include "../../utility/vin_log.h"
#include <linux/init.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/i2c.h>
#include <linux/delay.h>
#include <linux/videodev2.h>
#include <linux/clk.h>
#include <media/v4l2-device.h>
#include <media/v4l2-mediabus.h>
#include <linux/io.h>

#include "camera.h"
#include "sensor_helper.h"

MODULE_AUTHOR("opiha");
MODULE_DESCRIPTION("A low-level driver for OV5647 sensors");
MODULE_LICENSE("GPL");
MODULE_VERSION("1.0.1");

static int hold_power;
module_param(hold_power, int, 0644);
MODULE_PARM_DESC(hold_power, "debug: leave the sensor powered after PWR_OFF");

static int only_bus = -1;
module_param(only_bus, int, 0644);
MODULE_PARM_DESC(only_bus, "debug: only power the sensor on this i2c bus number (-1: all)");

/* Register tables are the mainline 25 MHz ones; a 24 MHz MCLK scales rates by 0.96 */
#define MCLK              (24*1000*1000)
#define V4L2_IDENT_SENSOR 0x5647

/*
 * Our nominal (default) frame rate.
 */

#define SENSOR_FRAME_RATE 30

/*
 * The OV5647 i2c address (8-bit form of 0x36)
 */
#define I2C_ADDR 0x6c

#define SENSOR_NAME "ov5647_mipi"
#define SENSOR_NAME_2 "ov5647_mipi_2"
#define SENSOR_NUM 0x2


/*
 * The default register settings
 */

static struct regval_list sensor_default_regs[] = {
	{0x0100, 0x00},
	{0x0103, 0x01},
	{REG_DLY, 0x0a},
};

static struct regval_list sensor_common_regs[] = {
	{0x3034, 0x1a},
	{0x3035, 0x21},
	{0x303c, 0x11},
	{0x3106, 0xf5},
	{0x3827, 0xec},
	{0x370c, 0x03},
	{0x5000, 0x06},
	{0x5003, 0x08},
	{0x5a00, 0x08},
	{0x3000, 0x00},
	{0x3001, 0x00},
	{0x3002, 0x00},
	{0x3016, 0x08},
	{0x3017, 0xe0},
	{0x3018, 0x44},
	{0x301c, 0xf8},
	{0x301d, 0xf0},
	{0x3a18, 0x00},
	{0x3a19, 0xf8},
	{0x3c01, 0x80},
	{0x3b07, 0x0c},
	{0x3630, 0x2e},
	{0x3632, 0xe2},
	{0x3633, 0x23},
	{0x3634, 0x44},
	{0x3636, 0x06},
	{0x3620, 0x64},
	{0x3621, 0xe0},
	{0x3600, 0x37},
	{0x3704, 0xa0},
	{0x3703, 0x5a},
	{0x3715, 0x78},
	{0x3717, 0x01},
	{0x3731, 0x02},
	{0x370b, 0x60},
	{0x3705, 0x1a},
	{0x3f05, 0x02},
	{0x3f06, 0x10},
	{0x3f01, 0x0a},
	{0x3a08, 0x01},
	{0x3a0f, 0x58},
	{0x3a10, 0x50},
	{0x3a1b, 0x58},
	{0x3a1e, 0x50},
	{0x3a11, 0x60},
	{0x3a1f, 0x28},
	{0x4001, 0x02},
	{0x4000, 0x09},
	{0x3503, 0x03},
};

static struct regval_list sensor_1080_regs[] = {
	{0x3036, 0x69},
	{0x3821, 0x02},
	{0x3820, 0x00},
	{0x3612, 0x5b},
	{0x3618, 0x04},
	{0x5002, 0x41},
	{0x3814, 0x11},
	{0x3815, 0x11},
	{0x3708, 0x64},
	{0x3709, 0x12},
	{0x3800, 0x01},
	{0x3801, 0x5c},
	{0x3802, 0x01},
	{0x3803, 0xb2},
	{0x3804, 0x08},
	{0x3805, 0xe3},
	{0x3806, 0x05},
	{0x3807, 0xf1},
	{0x3808, 0x07},
	{0x3809, 0x80},
	{0x380a, 0x04},
	{0x380b, 0x38},
	{0x3811, 0x04},
	{0x3813, 0x02},
	{0x3a09, 0x4b},
	{0x3a0a, 0x01},
	{0x3a0b, 0x13},
	{0x3a0d, 0x04},
	{0x3a0e, 0x03},
	{0x4004, 0x04},
	{0x4837, 0x19},
};

static struct regval_list sensor_972_regs[] = {
	{0x3036, 0x69},
	{0x3821, 0x03},
	{0x3820, 0x41},
	{0x3612, 0x59},
	{0x3618, 0x00},
	{0x5002, 0x41},
	{0x3800, 0x00},
	{0x3801, 0x00},
	{0x3802, 0x00},
	{0x3803, 0x00},
	{0x3804, 0x0a},
	{0x3805, 0x3f},
	{0x3806, 0x07},
	{0x3807, 0xa3},
	{0x3808, 0x05},
	{0x3809, 0x10},
	{0x380a, 0x03},
	{0x380b, 0xcc},
	{0x3811, 0x0c},
	{0x3813, 0x06},
	{0x3814, 0x31},
	{0x3815, 0x31},
	{0x3a09, 0x28},
	{0x3a0a, 0x00},
	{0x3a0b, 0xf6},
	{0x3a0d, 0x08},
	{0x3a0e, 0x06},
	{0x4004, 0x04},
	{0x4837, 0x16},
	{0x350a, 0x00},
	{0x350b, 0x10},
	{0x3500, 0x00},
	{0x3501, 0x1a},
	{0x3502, 0xf0},
	{0x3212, 0xa0},
};

static struct regval_list sensor_vga_regs[] = {
	{0x3036, 0x46},
	{0x3821, 0x03},
	{0x3820, 0x41},
	{0x3612, 0x59},
	{0x3618, 0x00},
	{0x3814, 0x35},
	{0x3815, 0x35},
	{0x3708, 0x64},
	{0x3709, 0x52},
	{0x3800, 0x00},
	{0x3801, 0x10},
	{0x3802, 0x00},
	{0x3803, 0x00},
	{0x3804, 0x0a},
	{0x3805, 0x2f},
	{0x3806, 0x07},
	{0x3807, 0x9f},
	{0x3808, 0x02},
	{0x3809, 0x80},
	{0x380a, 0x01},
	{0x380b, 0xe0},
	{0x3a09, 0x2e},
	{0x3a0a, 0x00},
	{0x3a0b, 0xfb},
	{0x3a0d, 0x02},
	{0x3a0e, 0x01},
	{0x4004, 0x02},
};

static struct regval_list sensor_fmt_raw[] = {
};

/*
 * Code for dealing with controls.
 * fill with different sensor module
 * different sensor module has different settings here
 * if not support the follow function ,retrun -EINVAL
 */

static int sensor_g_exp(struct v4l2_subdev *sd, __s32 *value)
{
	struct sensor_info *info = to_state(sd);

	*value = info->exp;
	sensor_dbg("sensor_get_exposure = %d\n", info->exp);
	return 0;
}

static int sensor_s_exp(struct v4l2_subdev *sd, unsigned int exp_val)
{
	unsigned char explow, expmid, exphigh;
	struct sensor_info *info = to_state(sd);

	if (exp_val > 0xfffff)
		exp_val = 0xfffff;
	if (exp_val < 7)
		exp_val = 7;

	exphigh = (unsigned char)((0x0f0000 & exp_val) >> 16);
	expmid = (unsigned char)((0x00ff00 & exp_val) >> 8);
	explow = (unsigned char)(0x0000ff & exp_val);

	sensor_write(sd, 0x3502, explow);
	sensor_write(sd, 0x3501, expmid);
	sensor_write(sd, 0x3500, exphigh);

	info->exp = exp_val;
	return 0;
}

static int sensor_g_gain(struct v4l2_subdev *sd, __s32 *value)
{
	struct sensor_info *info = to_state(sd);
	*value = info->gain;
	sensor_dbg("sensor_get_gain = %d\n", info->gain);
	return 0;
}

static int sensor_s_gain(struct v4l2_subdev *sd, unsigned int gain_val)
{
	struct sensor_info *info = to_state(sd);
	unsigned char gainlow = 0;
	unsigned char gainhigh = 0;

	if (gain_val < 1 * 16)
		gain_val = 16;
	if (gain_val > 64 * 16 - 1)
		gain_val = 64 * 16 - 1;

	gainlow = (unsigned char)(gain_val & 0xff);
	gainhigh = (unsigned char)((gain_val >> 8) & 0x3);

	sensor_write(sd, 0x350b, gainlow);
	sensor_write(sd, 0x350a, gainhigh);

	info->gain = gain_val;

	return 0;
}

static int ov5647_sensor_vts;
static int frame_length = 1104;
static int sensor_s_exp_gain(struct v4l2_subdev *sd,
				struct sensor_exp_gain *exp_gain)
{
	int exp_val, gain_val, shutter;
	unsigned char explow = 0, expmid = 0, exphigh = 0;
	unsigned char gainlow = 0, gainhigh = 0;
	struct sensor_info *info = to_state(sd);

	exp_val = exp_gain->exp_val;
	gain_val = exp_gain->gain_val;
	if (gain_val < 1*16)
		gain_val = 16;
	if (gain_val > 64*16-1)
		gain_val = 64*16-1;

	if (exp_val > 0xfffff)
		exp_val = 0xfffff;

	gainlow = (unsigned char)(gain_val & 0xff);
	gainhigh = (unsigned char)((gain_val >> 8)&0x3);

	exphigh	= (unsigned char)((0x0f0000&exp_val) >> 16);
	expmid	= (unsigned char)((0x00ff00&exp_val) >> 8);
	explow	= (unsigned char)((0x0000ff&exp_val));

	shutter = exp_val/16;
	if (shutter  > ov5647_sensor_vts - 4)
		frame_length = shutter + 4;
	else
		frame_length = ov5647_sensor_vts;

	sensor_write(sd, 0x3212, 0x00);/* enter group write */
	sensor_write(sd, 0x3503, 0x03);
	sensor_write(sd, 0x380f, (frame_length & 0xff));
	sensor_write(sd, 0x380e, (frame_length >> 8));
	sensor_write(sd, 0x350b, gainlow);
	sensor_write(sd, 0x350a, gainhigh);

	sensor_write(sd, 0x3502, explow);
	sensor_write(sd, 0x3501, expmid);
	sensor_write(sd, 0x3500, exphigh);
	sensor_write(sd, 0x3212, 0x10);/* end group write */
	sensor_write(sd, 0x3212, 0xa0);/* launch group write */
	info->exp = exp_val;
	info->gain = gain_val;
	return 0;
}

static int sensor_s_sw_stby(struct v4l2_subdev *sd, int on_off)
{
	int ret = 0;
	return ret;
}

/*
 * Stuff that knows about the sensor.
 */
static int sensor_power(struct v4l2_subdev *sd, int on)
{
	struct i2c_client *pwr_client = v4l2_get_subdevdata(sd);

	if (only_bus >= 0 && pwr_client->adapter->nr != only_bus)
		return 0;

	sensor_dbg("sensor_power\n");

	switch (on) {
	case STBY_ON:
		sensor_dbg("STBY_ON!\n");
		cci_lock(sd);
		sensor_s_sw_stby(sd, STBY_ON);
		usleep_range(1000, 1200);
		cci_unlock(sd);
		break;
	case STBY_OFF:
		sensor_dbg("STBY_OFF!\n");
		cci_lock(sd);
		usleep_range(1000, 1200);
		sensor_s_sw_stby(sd, STBY_OFF);
		cci_unlock(sd);
		break;
	case PWR_ON:
		sensor_dbg("PWR_ON!100\n");
		cci_lock(sd);
		vin_gpio_set_status(sd, PWDN, 1);
		vin_gpio_set_status(sd, RESET, 1);
		usleep_range(100, 120);
		vin_gpio_write(sd, PWDN, CSI_GPIO_LOW);
		vin_gpio_write(sd, RESET, CSI_GPIO_LOW);
		vin_gpio_write(sd, POWER_EN, CSI_GPIO_HIGH);
		vin_set_pmu_channel(sd, AFVDD, ON);
		vin_set_pmu_channel(sd, CAMERAVDD, ON);
		vin_set_pmu_channel(sd, IOVDD, ON);
		usleep_range(100, 120);
		vin_set_pmu_channel(sd, DVDD, ON);
		usleep_range(100, 120);
		vin_set_pmu_channel(sd, AVDD, ON);
		usleep_range(200, 220);
		vin_set_mclk_freq(sd, MCLK);
		vin_set_mclk(sd, ON);
		usleep_range(10000, 12000);
		vin_gpio_write(sd, PWDN, CSI_GPIO_HIGH);
		usleep_range(2000, 2200);
		vin_gpio_write(sd, RESET, CSI_GPIO_HIGH);
		usleep_range(25000, 26000);
		cci_unlock(sd);
		/* outputs on, then stream off to coax the MIPI lanes into LP-11
		 * (after cci_unlock: cci_lock holds the adapter lock, so an i2c
		 * transfer inside it deadlocks) */
		cci_write(sd, 0x3000, 0x0f);
		cci_write(sd, 0x3001, 0xff);
		cci_write(sd, 0x3002, 0xe4);
		cci_write(sd, 0x4800, 0x25);
		cci_write(sd, 0x4202, 0x0f);
		cci_write(sd, 0x300d, 0x01);
		break;
	case PWR_OFF:
		sensor_dbg("PWR_OFF!\n");
		if (hold_power) {
			sensor_err("hold_power set: leaving sensor powered\n");
			return 0;
		}
		cci_lock(sd);
		usleep_range(100, 120);
		vin_gpio_write(sd, PWDN, CSI_GPIO_LOW);
		vin_gpio_write(sd, RESET, CSI_GPIO_LOW);
		usleep_range(100, 120);
		vin_set_mclk(sd, OFF);
		vin_gpio_write(sd, POWER_EN, CSI_GPIO_LOW);
		vin_set_pmu_channel(sd, AVDD, OFF);
		vin_set_pmu_channel(sd, DVDD, OFF);
		vin_set_pmu_channel(sd, IOVDD, OFF);
		vin_set_pmu_channel(sd, CAMERAVDD, OFF);
		vin_set_pmu_channel(sd, AFVDD, OFF);
		usleep_range(100, 120);
		vin_gpio_write(sd, PWDN, CSI_GPIO_LOW);
		usleep_range(100, 120);
		cci_unlock(sd);
		break;
	default:
		return -EINVAL;
	}

	return 0;
}

static int sensor_reset(struct v4l2_subdev *sd, u32 val)
{
	switch (val) {
	case 0:
		vin_gpio_write(sd, RESET, CSI_GPIO_HIGH);
		usleep_range(100, 1200);
		break;
	case 1:
		vin_gpio_write(sd, RESET, CSI_GPIO_LOW);
		usleep_range(100, 1200);
		break;
	default:
		return -EINVAL;
	}
	return 0;
}

static int sensor_detect(struct v4l2_subdev *sd)
{
	data_type rdval;
	unsigned int SENSOR_ID = 0;
	sensor_read(sd, 0x300A, &rdval);
	SENSOR_ID |= (rdval << 8);
	sensor_read(sd, 0x300B, &rdval);
	SENSOR_ID |= (rdval);
	sensor_dbg("V4L2_IDENT_SENSOR = 0x%x\n", SENSOR_ID);
	if (SENSOR_ID == 0) {
		/* no ACK at all: keep going so the node registers for bring-up */
		sensor_err("ov5647 did not answer on i2c\n");
	} else if (SENSOR_ID != V4L2_IDENT_SENSOR) {
		sensor_err("ov5647 chip id 0x%x, expected 0x%x\n", SENSOR_ID, V4L2_IDENT_SENSOR);
		return -ENODEV;
	}

	return 0;
}

static int sensor_init(struct v4l2_subdev *sd, u32 val)
{
	int ret;
	struct sensor_info *info = to_state(sd);

	sensor_dbg("sensor_init\n");

	/* Make sure it is a target sensor */
	ret = sensor_detect(sd);
	if (ret) {
		sensor_err("chip found is not an target chip.\n");
		return ret;
	}

	info->focus_status = 0;
	info->low_speed = 0;
	info->width = 1920;
	info->height = 1080;
	info->hflip = 0;
	info->vflip = 0;

	info->tpf.numerator = 1;
	info->tpf.denominator = 30;	/* 30fps */

	info->preview_first_flag = 1;

	return 0;
}

static long sensor_ioctl(struct v4l2_subdev *sd, unsigned int cmd, void *arg)
{
	int ret = 0;
	struct sensor_info *info = to_state(sd);

	switch (cmd) {
	case GET_CURRENT_WIN_CFG:
		if (info->current_wins != NULL) {
			memcpy(arg, info->current_wins,
				sizeof(struct sensor_win_size));
			ret = 0;
		} else {
			sensor_err("empty wins!\n");
			ret = -1;
		}
		break;
	case SET_FPS:
		ret = 0;
		break;
	case VIDIOC_VIN_SENSOR_EXP_GAIN:
		ret = sensor_s_exp_gain(sd, (struct sensor_exp_gain *)arg);
		break;
	case VIDIOC_VIN_SENSOR_CFG_REQ:
		sensor_cfg_req(sd, (struct sensor_config *)arg);
		break;
	case VIDIOC_VIN_ACT_INIT:
		sensor_dbg("%s VIDIOC_VIN_ACT_INIT\n", __func__);
		ret = actuator_init(sd, (struct actuator_para *)arg);
		break;
	case VIDIOC_VIN_ACT_SET_CODE:
		ret = actuator_set_code(sd, (struct actuator_ctrl *)arg);
		break;
	case VIDIOC_VIN_FLASH_EN:
		ret = flash_en(sd, (struct flash_para *)arg);
		break;
	default:
		return -EINVAL;
	}
	return ret;
}

/*
 * Store information about the video data format.
 */
static struct sensor_format_struct sensor_formats[] = {
	{
		.desc = "Raw RGB Bayer",
		.mbus_code = MEDIA_BUS_FMT_SBGGR10_1X10,
		.regs = sensor_fmt_raw,
		.regs_size = ARRAY_SIZE(sensor_fmt_raw),
		.bpp = 1
	},
};
#define N_FMTS ARRAY_SIZE(sensor_formats)

/*
 * Then there is the issue of window sizes.  Try to capture the info here.
 */

static struct sensor_win_size sensor_win_sizes[] = {
	/* 1080p crop, ~31fps (84 MHz pclk at 24 MHz MCLK) */
	{
		.width      = 1920,
		.height     = 1080,
		.hoffset    = 0,
		.voffset    = 0,
		.hts        = 2416,
		.vts        = 1104,
		.pclk       = 84*1000*1000,
		.mipi_bps   = 420*1000*1000,
		.fps_fixed  = 30,
		.bin_factor = 1,
		.intg_min   = 1 << 4,
		.intg_max   = (1104 - 4) << 4,
		.gain_min   = 1 << 4,
		.gain_max   = 64 << 4,
		.regs       = sensor_1080_regs,
		.regs_size  = ARRAY_SIZE(sensor_1080_regs),
		.set_size   = NULL,
	},
	/* 2x2 binned full FOV, ~31fps */
	{
		.width      = 1296,
		.height     = 972,
		.hoffset    = 0,
		.voffset    = 0,
		.hts        = 1896,
		.vts        = 1435,
		.pclk       = 84*1000*1000,
		.mipi_bps   = 420*1000*1000,
		.fps_fixed  = 30,
		.bin_factor = 1,
		.intg_min   = 1 << 4,
		.intg_max   = (1435 - 4) << 4,
		.gain_min   = 1 << 4,
		.gain_max   = 64 << 4,
		.regs       = sensor_972_regs,
		.regs_size  = ARRAY_SIZE(sensor_972_regs),
		.set_size   = NULL,
	},
	/* VGA 2x2 binned+subsampled, ~60fps (56 MHz pclk) */
	{
		.width      = 640,
		.height     = 480,
		.hoffset    = 0,
		.voffset    = 0,
		.hts        = 1852,
		.vts        = 504,
		.pclk       = 56*1000*1000,
		.mipi_bps   = 280*1000*1000,
		.fps_fixed  = 60,
		.bin_factor = 1,
		.intg_min   = 1 << 4,
		.intg_max   = (504 - 4) << 4,
		.gain_min   = 1 << 4,
		.gain_max   = 64 << 4,
		.regs       = sensor_vga_regs,
		.regs_size  = ARRAY_SIZE(sensor_vga_regs),
		.set_size   = NULL,
	},
};

#define N_WIN_SIZES (ARRAY_SIZE(sensor_win_sizes))

static int sensor_reg_init(struct sensor_info *info)
{
	int ret;
	struct v4l2_subdev *sd = &info->sd;
	struct sensor_format_struct *sensor_fmt = info->fmt;
	struct sensor_win_size *wsize = info->current_wins;

	ret = sensor_write_array(sd, sensor_default_regs,
				ARRAY_SIZE(sensor_default_regs));
	if (ret < 0) {
		sensor_err("write sensor_default_regs error\n");
		return ret;
	}

	ret = sensor_write_array(sd, sensor_common_regs,
				ARRAY_SIZE(sensor_common_regs));
	if (ret < 0) {
		sensor_err("write sensor_common_regs error\n");
		return ret;
	}

	sensor_dbg("sensor_reg_init\n");

	sensor_write_array(sd, sensor_fmt->regs, sensor_fmt->regs_size);

	if (wsize->regs)
		sensor_write_array(sd, wsize->regs, wsize->regs_size);

	if (wsize->set_size)
		wsize->set_size(sd);

	info->width = wsize->width;
	info->height = wsize->height;
	ov5647_sensor_vts = wsize->vts;
	frame_length = wsize->vts;
	sensor_write(sd, 0x380f, (frame_length & 0xff));
	sensor_write(sd, 0x380e, (frame_length >> 8));
	sensor_s_exp(sd, info->exp);
	sensor_s_gain(sd, info->gain);

	/* stream on: standby off, continuous clock, bus idle, pad out enabled */
	sensor_write(sd, 0x0100, 0x01);
	sensor_write(sd, 0x4800, 0x04);
	sensor_write(sd, 0x4202, 0x00);
	sensor_write(sd, 0x300d, 0x00);

	sensor_dbg("s_fmt set width = %d, height = %d\n", wsize->width,
				wsize->height);

	return 0;
}

static int sensor_s_stream(struct v4l2_subdev *sd, int enable)
{
	struct sensor_info *info = to_state(sd);

	sensor_dbg("%s on = %d, %d*%d fps: %d code: %x\n", __func__, enable,
			info->current_wins->width, info->current_wins->height,
			info->current_wins->fps_fixed, info->fmt->mbus_code);

	if (!enable) {
		sensor_write(sd, 0x4800, 0x25);
		sensor_write(sd, 0x4202, 0x0f);
		sensor_write(sd, 0x300d, 0x01);
		return 0;
	}

	return sensor_reg_init(info);
}
static int sensor_g_mbus_config(struct v4l2_subdev *sd, unsigned int pad,
				struct v4l2_mbus_config *cfg)
{
	cfg->type = V4L2_MBUS_CSI2_DPHY;
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)
	cfg->bus.mipi_csi2.num_data_lanes = 0 | V4L2_MBUS_CSI2_2_LANE | V4L2_MBUS_CSI2_CHANNEL_0;
#else
	cfg->flags = 0 | V4L2_MBUS_CSI2_2_LANE | V4L2_MBUS_CSI2_CHANNEL_0;
#endif

	return 0;
}

static int sensor_g_ctrl(struct v4l2_ctrl *ctrl)
{
	struct sensor_info *info =
			container_of(ctrl->handler, struct sensor_info, handler);
	struct v4l2_subdev *sd = &info->sd;

	switch (ctrl->id) {
	case V4L2_CID_GAIN:
		return sensor_g_gain(sd, &ctrl->val);
	case V4L2_CID_EXPOSURE:
		return sensor_g_exp(sd, &ctrl->val);
	}
	return -EINVAL;
}

static int sensor_s_ctrl(struct v4l2_ctrl *ctrl)
{
	struct sensor_info *info =
			container_of(ctrl->handler, struct sensor_info, handler);
	struct v4l2_subdev *sd = &info->sd;

	switch (ctrl->id) {
	case V4L2_CID_GAIN:
		return sensor_s_gain(sd, ctrl->val);
	case V4L2_CID_EXPOSURE:
		return sensor_s_exp(sd, ctrl->val);
	}
	return -EINVAL;
}



/* ----------------------------------------------------------------------- */

static const struct v4l2_ctrl_ops sensor_ctrl_ops = {
	.g_volatile_ctrl = sensor_g_ctrl,
	.s_ctrl = sensor_s_ctrl,
};

static const struct v4l2_subdev_core_ops sensor_core_ops = {
	.reset = sensor_reset,
	.init = sensor_init,
	.s_power = sensor_power,
	.ioctl = sensor_ioctl,
#if IS_ENABLED(CONFIG_COMPAT)
	.compat_ioctl32 = sensor_compat_ioctl32,
#endif
};

static const struct v4l2_subdev_video_ops sensor_video_ops = {
	.s_stream = sensor_s_stream,
};

static const struct v4l2_subdev_pad_ops sensor_pad_ops = {
	.enum_mbus_code = sensor_enum_mbus_code,
	.enum_frame_size = sensor_enum_frame_size,
	.enum_frame_interval = sensor_enum_frame_interval,
	.get_fmt = sensor_get_fmt,
	.set_fmt = sensor_set_fmt,
	.get_mbus_config = sensor_g_mbus_config,
};

static const struct v4l2_subdev_ops sensor_ops = {
	.core = &sensor_core_ops,
	.video = &sensor_video_ops,
	.pad = &sensor_pad_ops,
};

/* ----------------------------------------------------------------------- */
/* Two names so the VIN core can tell the two camera slots apart (as imx219 does) */
static struct cci_driver cci_drv[] = {
	{
		.name = SENSOR_NAME,
		.addr_width = CCI_BITS_16,
		.data_width = CCI_BITS_8,
	}, {
		.name = SENSOR_NAME_2,
		.addr_width = CCI_BITS_16,
		.data_width = CCI_BITS_8,
	},
};

static const struct v4l2_ctrl_config sensor_custom_ctrls[] = {
	{
		.ops = &sensor_ctrl_ops,
		.id = V4L2_CID_FRAME_RATE,
		.name = "frame rate",
		.type = V4L2_CTRL_TYPE_INTEGER,
		.min = 15,
		.max = 120,
		.step = 1,
		.def = 120,
	},
};

static int sensor_init_controls(struct v4l2_subdev *sd, const struct v4l2_ctrl_ops *ops)
{
	struct sensor_info *info = to_state(sd);
	struct v4l2_ctrl_handler *handler = &info->handler;
	struct v4l2_ctrl *ctrl;
	int i;
	int ret = 0;

	v4l2_ctrl_handler_init(handler, 2 + ARRAY_SIZE(sensor_custom_ctrls));

	v4l2_ctrl_new_std(handler, ops, V4L2_CID_GAIN, 1 * 1600,
				256 * 1600, 1, 1 * 1600);
	ctrl = v4l2_ctrl_new_std(handler, ops, V4L2_CID_EXPOSURE, 0,
				65536 * 16, 1, 0);
	if (ctrl != NULL)
		ctrl->flags |= V4L2_CTRL_FLAG_VOLATILE;
	for (i = 0; i < ARRAY_SIZE(sensor_custom_ctrls); i++)
		v4l2_ctrl_new_custom(handler, &sensor_custom_ctrls[i], NULL);

	if (handler->error) {
		ret = handler->error;
		v4l2_ctrl_handler_free(handler);
	}

	sd->ctrl_handler = handler;

	return ret;
}

static int sensor_dev_id;

#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)
static int sensor_probe(struct i2c_client *client)
#else
static int sensor_probe(struct i2c_client *client,
			const struct i2c_device_id *id)
#endif
{
	struct v4l2_subdev *sd;
	struct sensor_info *info;
	int i;

	info = kzalloc(sizeof(struct sensor_info), GFP_KERNEL);
	if (info == NULL)
		return -ENOMEM;
	sd = &info->sd;

	if (client) {
		for (i = 0; i < SENSOR_NUM; i++) {
			if (!strcmp(cci_drv[i].name, client->name))
				break;
		}
		cci_dev_probe_helper(sd, client, &sensor_ops, &cci_drv[i]);
	} else {
		cci_dev_probe_helper(sd, client, &sensor_ops, &cci_drv[sensor_dev_id++]);
	}
	sensor_init_controls(sd, &sensor_ctrl_ops);

	mutex_init(&info->lock);
#if IS_ENABLED(CONFIG_SAME_I2C)
	info->sensor_i2c_addr = I2C_ADDR >> 1;
#endif
	info->fmt = &sensor_formats[0];
	info->fmt_pt = &sensor_formats[0];
	info->win_pt = &sensor_win_sizes[0];
	info->fmt_num = N_FMTS;
	info->win_size_num = N_WIN_SIZES;
	info->sensor_field = V4L2_FIELD_NONE;
	info->stream_seq = MIPI_BEFORE_SENSOR;
	info->af_first_flag = 1;
	info->exp = 15616;
	info->gain = 64;

	return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 1, 0)
static int sensor_remove(struct i2c_client *client)
#else
static void sensor_remove(struct i2c_client *client)
#endif
{
	struct v4l2_subdev *sd;

	int i;

	if (client) {
		for (i = 0; i < SENSOR_NUM; i++) {
			if (!strcmp(cci_drv[i].name, client->name))
				break;
		}
		sd = cci_dev_remove_helper(client, &cci_drv[i]);
	} else {
		sd = cci_dev_remove_helper(client, &cci_drv[sensor_dev_id++]);
	}

	kfree(to_state(sd));
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 1, 0)
	return 0;
#endif
}

static const struct i2c_device_id sensor_id[] = {
	{SENSOR_NAME, 0},
	{}
};

static const struct i2c_device_id sensor_id_2[] = {
	{SENSOR_NAME_2, 0},
	{}
};

MODULE_DEVICE_TABLE(i2c, sensor_id);
MODULE_DEVICE_TABLE(i2c, sensor_id_2);

static struct i2c_driver sensor_driver[] = {
	{
		.driver = {
			   .owner = THIS_MODULE,
			   .name = SENSOR_NAME,
			   },
		.probe = sensor_probe,
		.remove = sensor_remove,
		.id_table = sensor_id,
	}, {
		.driver = {
			   .owner = THIS_MODULE,
			   .name = SENSOR_NAME_2,
			   },
		.probe = sensor_probe,
		.remove = sensor_remove,
		.id_table = sensor_id_2,
	},
};
static __init int init_sensor(void)
{
	int i, ret = 0;

	sensor_dev_id = 0;

	for (i = 0; i < SENSOR_NUM; i++)
		ret = cci_dev_init_helper(&sensor_driver[i]);

	return ret;
}

static __exit void exit_sensor(void)
{
	int i;

	sensor_dev_id = 0;

	for (i = 0; i < SENSOR_NUM; i++)
		cci_dev_exit_helper(&sensor_driver[i]);
}

VIN_INIT_DRIVERS(init_sensor);
module_exit(exit_sensor);
