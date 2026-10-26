/* SPDX-License-Identifier: GPL-2.0-only */
/* Local shim: the public kit omits these two kernel headers; the UEFI port
   only needs the printk macros to land in the run report. */
#pragma once
#include "../../port.h"

#define pr_info(...) GuLog(__VA_ARGS__)
#define pr_err(...) GuLog(__VA_ARGS__)
#define pr_warn(...) GuLog(__VA_ARGS__)
#define dev_info(dev, ...) GuLog(__VA_ARGS__)
#define dev_err(dev, ...) GuLog(__VA_ARGS__)
