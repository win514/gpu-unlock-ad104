/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once
#include "port.h"

/* Read-only collection pass: enumerates PCI, picks the single card matching
   GU_BOARD_ID, then reports identity, BAR, cold registers, ROM and PROM hashes
   into REPORT.TXT and PROFILE.TXT.  It never writes MMIO, never claims the
   controller, never loads assets and never issues a firmware transaction. */
EFI_STATUS GuDiagRun(VOID);
