/* SPDX-License-Identifier: GPL-2.0-only */
/* Local shim: stable Linux errno values used by the retained transaction. */
#pragma once
#include "../compat.h"

#ifndef EPERM
#define EPERM 1
#endif
#ifndef ENOENT
#define ENOENT 2
#endif
#ifndef EIO
#define EIO 5
#endif
#ifndef EAGAIN
#define EAGAIN 11
#endif
#ifndef ENOMEM
#define ENOMEM 12
#endif
#ifndef EACCES
#define EACCES 13
#endif
#ifndef EBUSY
#define EBUSY 16
#endif
#ifndef ENODEV
#define ENODEV 19
#endif
#ifndef EINVAL
#define EINVAL 22
#endif
#ifndef ENOSYS
#define ENOSYS 38
#endif
#ifndef ETIMEDOUT
#define ETIMEDOUT 110
#endif
#ifndef EOPNOTSUPP
#define EOPNOTSUPP 95
#endif
#ifndef ENOTSUPP
#define ENOTSUPP 524
#endif
