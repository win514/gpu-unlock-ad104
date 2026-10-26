/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Read-only profile collector for a re-packaged single-board build.
 * Everything it prints is later turned into board_profile.h by build.py.
 */
#include "diag.h"
#include "app_io.h"
#include "board_profile.h"
#include "format.h"
#include "sha256.h"
#include <Protocol/PciIo.h>
#include <IndustryStandard/Acpi10.h>

#define GU_BY_PROTOCOL 2
#define GU_DIAG_TEXT_BYTES 16384U

static EFI_GUID PciGuid = EFI_PCI_IO_PROTOCOL_GUID;
static const char HexDigits[] = "0123456789abcdef";
static char *Text;
static UINTN TextLen, TextCap;

static VOID TxtStr(const char *s) {
  while (*s && TextLen + 1 < TextCap) Text[TextLen++] = *s++;
  if (TextCap) Text[TextLen] = 0;
}

/* One line to both REPORT.TXT and the machine-readable PROFILE.TXT. */
static VOID Both(const char *Format, ...) {
  char line[512];
  va_list a;
  size_t n;
  va_start(a, Format);
  n = GuFormatV(line, sizeof(line), Format, a);
  va_end(a);
  if (n >= sizeof(line)) n = sizeof(line) - 1;
  line[n] = 0;
  TxtStr(line);
  TxtStr("\n");
  GuLog("%s\n", line);
}

static VOID HashLine(const char *Name, const VOID *Data, UINTN Bytes) {
  UINT8 digest[32];
  char hex[65];
  GuSha256(Data, Bytes, digest);
  for (UINTN i = 0; i < 32; i++) {
    hex[2 * i] = HexDigits[digest[i] >> 4];
    hex[2 * i + 1] = HexDigits[digest[i] & 15];
  }
  hex[64] = 0;
  Both("%s_bytes=%u", Name, (unsigned)Bytes);
  Both("%s_sha256=%s", Name, hex);
}

EFI_STATUS GuDiagRun(VOID) {
  EFI_BOOT_SERVICES *bs = Gu.bs;
  EFI_HANDLE *handles = NULL;
  UINTN count = 0, found = 0, segment = 0, bus = 0, device = 0, function = 0;
  EFI_STATUS status;
  UINT32 config[64];
  UINT32 id;
  UINT8 *prom = NULL;

  if (!bs) return EFI_INVALID_PARAMETER;
  TextCap = GU_DIAG_TEXT_BYTES;
  Text = GuAlloc(TextCap);
  if (!Text) return EFI_OUT_OF_RESOURCES;
  TextLen = 0;
  Text[0] = 0;
  TxtStr("format=gu-profile-1\n");
  Both("diag=start mode=read-only board=%#x", GU_BOARD_ID);

  status = bs->LocateHandleBuffer(GU_BY_PROTOCOL, &PciGuid, NULL, &count, &handles);
  Both("pci_handles status=%#llx count=%u", (unsigned long long)status, (unsigned)count);
  if (EFI_ERROR(status) || !handles || !count || count > 256) {
    if (handles) GuFree(handles);
    Both("diag=abort reason=enumeration");
    GuSaveText(L"PROFILE.TXT", Text, TextLen);
    return EFI_NOT_FOUND;
  }

  for (UINTN i = 0; i < count; i++) {
    EFI_PCI_IO_PROTOCOL *pci = NULL;
    id = 0;
    if (EFI_ERROR(bs->HandleProtocol(handles[i], &PciGuid, (VOID **)&pci)) || !pci) continue;
    if (EFI_ERROR(pci->Pci.Read(pci, EfiPciIoWidthUint32, 0, 1, &id))) continue;
    Both("pci[%u]=%#x", (unsigned)i, id);
    if (id == GU_BOARD_ID) {
      found++;
      Gu.handle = handles[i];
      Gu.pci = pci;
    }
  }
  GuFree(handles);
  if (found != 1) {
    Both("diag=abort reason=target_matches found=%u", (unsigned)found);
    GuSaveText(L"PROFILE.TXT", Text, TextLen);
    return EFI_UNSUPPORTED;
  }

  for (UINTN i = 0; i < 64; i++)
    if (EFI_ERROR(GuConfigRead(EfiPciIoWidthUint32, (UINT32)i * 4, &config[i]))) {
      Both("diag=abort reason=config_read offset=%#llx", (unsigned long long)(i * 4));
      GuSaveText(L"PROFILE.TXT", Text, TextLen);
      return EFI_DEVICE_ERROR;
    }
  for (UINTN i = 0; i < 64; i += 4)
    Both("config_%02x=%08x %08x %08x %08x", (unsigned)(i * 4),
         config[i], config[i + 1], config[i + 2], config[i + 3]);

  status = Gu.pci->GetLocation(Gu.pci, &segment, &bus, &device, &function);
  if (!EFI_ERROR(status))
    Both("bdf=%04x:%02x:%02x.%x", (unsigned)segment, (unsigned)bus,
         (unsigned)device, (unsigned)function);
  Both("device_id=%04x:%04x", (unsigned)(config[0] & 0xffff), (unsigned)(config[0] >> 16));
  Both("subsystem_id=%04x:%04x", (unsigned)(config[0xb] & 0xffff), (unsigned)(config[0xb] >> 16));
  Both("class_revision=%08x", config[2u]);
  Both("revision=%#x", (unsigned)(config[2] & 0xff));

  {
    EFI_ACPI_ADDRESS_SPACE_DESCRIPTOR *r = NULL;
    status = Gu.pci->GetBarAttributes(Gu.pci, 0, NULL, (VOID **)&r);
    Both("bar0_query status=%#llx", (unsigned long long)status);
    if (!EFI_ERROR(status) && r) {
      Both("bar0_addr=%#llx bar0_size=%#llx bar0_max=%#llx gran=%#llx kind=%u",
           (unsigned long long)r->AddrRangeMin, (unsigned long long)r->AddrLen,
           (unsigned long long)r->AddrRangeMax,
           (unsigned long long)r->AddrSpaceGranularity, (unsigned)r->ResType);
      Gu.bar_base = r->AddrRangeMin;
      Gu.bar_size = r->AddrLen;
      GuFree(r);
    }
  }
  Both("rom_size=%#llx", (unsigned long long)Gu.pci->RomSize);
  if (Gu.pci->RomImage && Gu.pci->RomSize) HashLine("rom", Gu.pci->RomImage, Gu.pci->RomSize);

  if (!Gu.bar_base || !Gu.bar_size) {
    Both("diag=partial reason=no_bar0");
    GuSaveText(L"PROFILE.TXT", Text, TextLen);
    return EFI_SUCCESS;
  }

  {
    static const struct { const char *name; UINT32 offset; } regs[] = {
      {"chip", 0x000000}, {"wpr_cfg", 0x1fa7cc}, {"fbpa", 0x9a0148},
      {"wpr", 0x1fa7c4}, {"feat_plm", 0x823804}, {"effective", 0x823818},
      {"ss0", 0x82381c}, {"ss1", 0x823820}, {"wpr2_lo", 0x1fa824},
      {"wpr2_hi", 0x1fa828}, {"vram", 0x1183a4}, {"sec2_cpuctl", 0x840100},
      {"sec2_mailbox0", 0x840040}, {"sec2_mailbox1", 0x840044},
      {"sec2_debuginfo", 0x840094}, {"sec2_reset", 0x8403c0},
      {"sec2_reset_plm", 0x8403c4}, {"bcr_ctrl", 0x841668},
      {"dmactl", 0x84010c}, {"dmatrfcmd", 0x840118}, {"source_enable", 0x823b00},
    };
    UINT32 value[sizeof(regs) / sizeof(regs[0])];
    for (UINTN i = 0; i < sizeof(regs) / sizeof(regs[0]); i++) {
      if ((UINT64)regs[i].offset + 4 > Gu.bar_size) { Gu.fault = TRUE; value[i] = 0xffffffffU; break; }
      value[i] = GuRead32(regs[i].offset);
      Both("reg_%s=%#x", regs[i].name, value[i]);
    }
    if (Gu.fault) Both("reg_read_fault=1");

    /* ------------------------------------------------------------------
       Pin-independent environment gates.

       Every failure mode that cost a reboot during bring-up is checked
       here in the same pass, so a first boot reports all of them at once
       instead of one per attempt. Nothing here writes to the device.
       ------------------------------------------------------------------ */
    const UINT32 chip = value[0], feat = value[4], ss0 = value[6], ss1 = value[7];
    const UINT32 wpr2_hi = value[9];
    UINT32 class_dword = config[2];
    const BOOLEAN class_ok = (class_dword & 0xffff0000U) == 0x03000000U;
    const BOOLEAN revision_known = (class_dword & 0xffU) != 0U;
    const BOOLEAN chip_ad10x = (chip & 0xffff0000U) >= 0x19000000U &&
                               (chip & 0xffff0000U) <= 0x199f0000U;
    const BOOLEAN bar_16m = Gu.bar_size == 0x1000000ULL;
    const BOOLEAN bar_mapped = Gu.bar_base != 0 && Gu.bar_size != 0;
    const BOOLEAN wpr2_clear = (wpr2_hi >> 4) == 0;
    const BOOLEAN not_already_unlocked = (ss0 & 0x88888888U) == 0;
    const BOOLEAN ss1_cold_like = ss1 == 0x7U || ss1 == 0x0U;
    const BOOLEAN plm_cold_like = feat == 0xffffff8fU;
    const BOOLEAN rom_present = Gu.pci->RomImage != NULL && Gu.pci->RomSize >= 0x10000ULL;

    Both("--- preflight: pin-independent gates ---");
    Both("gate class_display    = %s", class_ok ? "PASS" : "FAIL");
    Both("gate revision_present = %s", revision_known ? "PASS" : "FAIL");
    Both("gate chip_is_ad10x    = %s", chip_ad10x ? "PASS" : "FAIL");
    Both("gate bar0_mapped      = %s", bar_mapped ? "PASS" : "FAIL");
    Both("gate bar0_is_16mib    = %s", bar_16m ? "PASS" : "FAIL");
    Both("gate wpr2_released    = %s", wpr2_clear ? "PASS" : "FAIL");
    Both("gate not_unlocked_yet = %s", not_already_unlocked ? "PASS" : "FAIL");
    Both("gate ss1_cold_like    = %s", ss1_cold_like ? "PASS" : "FAIL");
    Both("gate feat_plm_cold    = %s", plm_cold_like ? "PASS" : "FAIL");
    Both("gate rom_readable     = %s", rom_present ? "PASS" : "FAIL");
    Both("info vram_encoding   = %#x (%u MiB) - pin as GU_VRAM_MIB", value[10], value[10]);
    if (!wpr2_clear)
      Both("note wpr2_released=FAIL means the GSP still owns its window: a warm reboot was used, power off for 30 s");
    if (!bar_16m)
      Both("note bar0_is_16mib=FAIL: pci_unlock pins GU_BAR0_SIZE; update it only after understanding why it differs");
    if (!chip_ad10x)
      Both("note chip_is_ad10x=FAIL: this is not an Ada AD10x part, stop here");
    Both("--- end preflight ---");
  }

  prom = GuAlloc(1048576);
  if (prom) {
    static const UINT32 candidates[] = {0x300000U, 0x200000U, 0x100000U, 0x0U};
    for (UINTN i = 0; i < sizeof(candidates) / sizeof(candidates[0]); i++) {
      UINT32 off = candidates[i];
      char name[32];
      if ((UINT64)off + 1048576 > Gu.bar_size || Gu.fault) continue;
      GuCopyFromIo(prom, (VOID *)(UINTN)(Gu.bar_base + off), 1048576);
      if (Gu.fault) { Both("prom_%06x=fault", (unsigned)off); break; }
      name[0] = 'p'; name[1] = 'r'; name[2] = 'o'; name[3] = 'm';
      name[4] = '_'; name[5] = (char)('0' + (int)i); name[6] = 0;
      Both("%s_offset=%#x first=%08x %08x %08x %08x", name, (unsigned)off,
           ((const UINT32 *)prom)[0], ((const UINT32 *)prom)[1],
           ((const UINT32 *)prom)[2], ((const UINT32 *)prom)[3]);
      HashLine(name, prom, 1048576);
    }
    GuFree(prom);
  }

  Both("diag=done rows_ok=1");
  GuSaveText(L"PROFILE.TXT", Text, TextLen);
  return EFI_SUCCESS;
}
