#!/usr/bin/env python3
"""HISTORICAL RECORD - do not run against this tree.

The substitutions below were applied to the unmodified donor sources to produce
`src/unlock/`. The tree already contains them, so re-running this file will fail
its own assertions. It is kept so each change is auditable and reproducible
against a fresh checkout of the donor project.

Original header follows.

"""Re-packaging patch set: turn the pinned AD103 RTX 4080 UEFI port into a
board-parameterised AD102-family port driven by board_profile.h.

Every substitution asserts that it applied exactly once, so the patch is
reproducible and fails loudly when the upstream text changes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "src" / "unlock"


def sub(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text()
    found = text.count(old)
    if found != count:
        sys.exit(f"{path.name}: expected {count} occurrences, found {found}\n---\n{old[:200]}")
    path.write_text(text.replace(old, new))
    print(f"patched {path.name}: {old.splitlines()[0][:60]}...")


# ---------------------------------------------------------------- port.h
sub(
    ROOT / "port.h",
    '''#define GU_BOARD_ID 0x270410deU
#define GU_BOARD_SUBSYSTEM 0x179510deU
#define GU_BOARD_CHIP 0x193000a1U''',
    '''#include "board_profile.h"''',
)

# ---------------------------------------------------------- prom_profile.h
(ROOT / "prom_profile.h").write_text(
    '''#ifndef GU_PROM_PROFILE_H
#define GU_PROM_PROFILE_H
/* Re-packaged port: PROM view geometry comes from board_profile.h. */
#include "board_profile.h"
#endif
'''
)
print("rewrote prom_profile.h")

# ----------------------------------------------------------- port.c identity
sub(
    ROOT / "port.c",
    '''BOOLEAN GuTargetConfig(const UINT32 *C, UINTN S, UINTN B, UINTN D, UINTN F) {
  return C && !S && B==1 && !D && !F && C[0]==GU_BOARD_ID &&
    C[11]==GU_BOARD_SUBSYSTEM && (C[2]>>24)==3 && !((C[3]>>16)&0x7f);
}''',
    '''BOOLEAN GuTargetConfig(const UINT32 *C, UINTN S, UINTN B, UINTN D, UINTN F) {
  /* Re-packaged: the BDF is whatever the firmware assigned; identity is the
     pinned device/subsystem pair and the single-match rule in FindTarget. */
  (void)S; (void)B; (void)D; (void)F;
  return C && C[0]==GU_BOARD_ID && C[11]==GU_BOARD_SUBSYSTEM &&
    (C[2]>>24)==3 && !((C[3]>>16)&0x7f);
}''',
)

# ------------------------------------------------------------ checks.c identity
sub(
    ROOT / "checks.c",
    '''  if (Config == NULL || Segment != 0 || Bus != 1 || Device != 0 || Function != 0)
    return FALSE;''',
    '''  (void)Segment; (void)Bus; (void)Device; (void)Function;
  if (Config == NULL)
    return FALSE;''',
)

# ------------------------------------------------------------ app.c includes
sub(
    ROOT / "app.c",
    '''#include "prom_profile.h"''',
    '''#include "prom_profile.h"
#include "diag.h"''',
)

# --------------------------------------------------------- app.c ConfigCheck
sub(
    ROOT / "app.c",
    '''  BOOLEAN valid=checked && config[2]==0x030000a1 && config[0xc8/4]==0x00050011 &&
    config[0x10/4]==0x80000000 && !(config[(caps.pcie+8)/4]&0x00200000U);''',
    '''  /* Re-packaged: class/revision/BAR identity comes from board_profile.h. */
  BOOLEAN valid=checked && (config[2]&0xffffff00U)==0x03000000U &&
    (GU_BOARD_REVISION==0xffU || (config[2]&0xffU)==GU_BOARD_REVISION) &&
    (GU_BAR0_ADDR==0 || config[0x10/4]==(UINT32)GU_BAR0_ADDR) &&
    !(config[(caps.pcie+8)/4]&0x00200000U);''',
)

# ------------------------------------------------------------ app.c BarCheck
sub(
    ROOT / "app.c",
    '''    if(!r || r->Desc!=ACPI_ADDRESS_SPACE_DESCRIPTOR || r->Len!=sizeof(*r)-3 || r->ResType!=0 ||
      r->AddrRangeMin!=0x80000000 || r->AddrLen!=0x1000000 || r->AddrTranslationOffset ||
      /* UEFI describes an inclusive end; pinned EDK2 PciBusDxe instead returns
         PciBar.Alignment. Both representations describe this exact 16 MiB BAR. */
      (r->AddrRangeMax!=0x80ffffff && r->AddrRangeMax!=0x00ffffff) ||
      r->AddrSpaceGranularity!=32 || ((UINT8 *)(r+1))[0]!=ACPI_END_TAG_DESCRIPTOR)status=EFI_UNSUPPORTED;''',
    '''    /* Re-packaged: address and length gates are optional (0 disables) so a
       different board can be profiled before its BAR is pinned. */
    if(!r || r->Desc!=ACPI_ADDRESS_SPACE_DESCRIPTOR || r->Len!=sizeof(*r)-3 || r->ResType!=0 ||
      (GU_BAR0_ADDR && r->AddrRangeMin!=GU_BAR0_ADDR) ||
      (GU_BAR0_SIZE && r->AddrLen!=GU_BAR0_SIZE) || r->AddrTranslationOffset ||
      /* UEFI describes an inclusive end; pinned EDK2 PciBusDxe instead returns
         PciBar.Alignment. Both representations describe this exact BAR. */
      (GU_BAR0_SIZE && GU_BAR0_ADDR &&
        r->AddrRangeMax!=GU_BAR0_ADDR+GU_BAR0_SIZE-1 && r->AddrRangeMax!=GU_BAR0_SIZE-1) ||
      r->AddrSpaceGranularity!=32 || ((UINT8 *)(r+1))[0]!=ACPI_END_TAG_DESCRIPTOR)status=EFI_UNSUPPORTED;''',
)

# ------------------------------------------------------------ app.c ColdCheck
sub(
    ROOT / "app.c",
    '''  if(chip!=GU_BOARD_CHIP)return EFI_UNSUPPORTED;''',
    '''  if(GU_BOARD_CHIP && chip!=GU_BOARD_CHIP)return EFI_UNSUPPORTED;''',
)
sub(
    ROOT / "app.c",
    '''  if(Gu.fault || gpu_unlock_gfw_assess(&s) || hi>>4 || plm!=0xffffff8f ||
    (ss0&0x88888888U) || ss1!=7 || (vram!=0x7ff8 && vram!=0x8000))return EFI_NOT_READY;''',
    '''  /* Re-packaged: each cold-state expectation is a board_profile.h value.
     A zero value records the observation instead of gating on it. */
  if(Gu.fault || gpu_unlock_gfw_assess(&s) || hi>>4 ||
    (GU_PLM_FEAT && plm!=GU_PLM_FEAT) ||
    (ss0&GU_SS0_LOCKED_MASK) ||
    (GU_SS1_COLD && ss1!=GU_SS1_COLD) ||
    (GU_VRAM_MIB && vram!=GU_VRAM_MIB))return EFI_NOT_READY;''',
)

# ------------------------------------------------------------ app.c PromCheck
sub(
    ROOT / "app.c",
    '''  if(!Gu.pci->RomImage || Gu.pci->RomSize!=0x24c00 ||
     !GuHashMatches(Gu.pci->RomImage,0x24c00,"c252043215d894318657580baf9c80c3a7bd508337e8ba15f469fb2e2e490102"))return EFI_CRC_ERROR;''',
    '''  /* Re-packaged: ROM size and digest are optional gates from board_profile.h. */
  if(!Gu.pci->RomImage || (GU_ROM_SIZE && Gu.pci->RomSize!=GU_ROM_SIZE) ||
     (GU_ROM_SHA256[0] && !GuHashMatches(Gu.pci->RomImage,Gu.pci->RomSize,GU_ROM_SHA256)))
    return EFI_CRC_ERROR;''',
)
sub(
    ROOT / "app.c",
    '''  BOOLEAN good=!Gu.fault && GuHashMatches(prom,GU_PROM_VIEW_BYTES,GU_PROM_VIEW_SHA256);''',
    '''  BOOLEAN good=!Gu.fault;
  if(good && GU_PROM_VIEW_BYTES && GU_PROM_VIEW_SHA256[0])
    good=GuHashMatches(prom,GU_PROM_VIEW_BYTES,GU_PROM_VIEW_SHA256);''',
)

# ------------------------------------------------------------ app.c Arm text
sub(
    ROOT / "app.c",
    '''  GuLogText("READY: RTX 4080 AD103 32GB / AD102 PLM+SS EXPERIMENT v0.4.17 / Windows preloaded.\\n");''',
    '''  GuLogText("READY: re-packaged AD102-family PLM+SS port v1.0.0 / Windows preloaded.\\n");''',
)

# ----------------------------------------------------- app.c EfiMain diag hook
sub(
    ROOT / "app.c",
    '''  Stage="usb-log";EFI_STATUS status=GuIoOpen(Image,St);BOOLEAN attempted=FALSE,release_attempted=FALSE;
  if(EFI_ERROR(status))goto finish;''',
    '''  Stage="usb-log";EFI_STATUS status=GuIoOpen(Image,St);
  BOOLEAN attempted=FALSE,release_attempted=FALSE;
  if(EFI_ERROR(status))goto finish;''',
)
sub(
    ROOT / "app.c",
    '''  Stage="watchdog";status=Step(Gu.bs->SetWatchdogTimer(0,0,0,NULL));if(EFI_ERROR(status))goto finish;''',
    '''  Stage="watchdog";status=Step(Gu.bs->SetWatchdogTimer(0,0,0,NULL));if(EFI_ERROR(status))goto finish;
#if GU_DIAG_MODE
  /* Read-only profile build: no ownership claim, no assets, no MMIO writes. */
  Stage="diag-profile";status=Step(GuDiagRun());goto finish;
#else''',
)
sub(
    ROOT / "app.c",
    '''  status=result?EFI_DEVICE_ERROR:EFI_SUCCESS;
finish:''',
    '''  status=result?EFI_DEVICE_ERROR:EFI_SUCCESS;
#endif /* GU_DIAG_MODE */
finish:''',
)

# --------------------------------------------------------------- app_io.c io
sub(
    ROOT / "app_io.c",
    '''  status=Root->Open(Root,&Parent,L"\\\\RTX4080-EXPERIMENT",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);''',
    '''  status=Root->Open(Root,&Parent,GU_RUN_DIR_W,EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0);''',
)
sub(
    ROOT / "app_io.c",
    '''    GuLog("RTX4080 AD103 / AD102 PLM+SS experimental port v0.4.18\\nRUN%02u\\n''',
    '''    GuLog("GU-PROFILE re-packaged AD102-family PLM+SS port v1.0.0 board=%#x\\nRUN%02u\\n''',
)
# --------------------------------------------------- app_io.c GuSaveText add
save_text = '''
EFI_STATUS GuSaveText(const CHAR16 *Name,const char *Data,UINTN Bytes) {
  EFI_FILE_PROTOCOL *file=NULL;EFI_STATUS status;
  if(!Run || !Name || !Data)return EFI_INVALID_PARAMETER;
  status=Run->Open(Run,&file,Name,EFI_FILE_MODE_READ,0);
  if(!EFI_ERROR(status)){if(file)file->Close(file);return EFI_ALREADY_STARTED;}
  if(status!=EFI_NOT_FOUND)return status;
  status=Run->Open(Run,&file,Name,EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,0);
  if(EFI_ERROR(status) || !file)return EFI_ERROR(status)?status:EFI_DEVICE_ERROR;
  UINTN written=Bytes;
  status=file->Write(file,&written,(VOID *)Data);
  if(!EFI_ERROR(status) && written!=Bytes)status=EFI_BAD_BUFFER_SIZE;
  if(!EFI_ERROR(status))status=file->Flush(file);
  EFI_STATUS closed=file->Close(file);
  return EFI_ERROR(status)?status:closed;
}
'''
io = ROOT / "app_io.c"
text = io.read_text()
anchor = "EFI_STATUS GuSavePromDump(const VOID *Data,UINTN Size) {"
if "GuSaveText(" not in text:
    text = text.replace(anchor, save_text.strip() + "\n" + anchor, 1)
    io.write_text(text)
    print("patched app_io.c: added GuSaveText")

# ------------------------------------------------------------- app_io.h decl
h = ROOT / "app_io.h"
text = h.read_text()
if "GuSaveText" not in text:
    text = text.replace(
        "EFI_STATUS GuSavePromDump(const VOID *Data,UINTN Size);",
        "EFI_STATUS GuSavePromDump(const VOID *Data,UINTN Size);\nEFI_STATUS GuSaveText(const CHAR16 *Name,const char *Data,UINTN Bytes);",
        1,
    )
    h.write_text(text)
    print("patched app_io.h: declared GuSaveText")

print("all patches applied")
