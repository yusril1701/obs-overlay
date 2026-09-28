# Membangun file .exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

atau klik dua kali `packaging\build.bat`. Hasil: `packaging\dist\ObsOverlay\ObsOverlay.exe`.

---

## Yang dilakukan skrip build

1. Membuat venv terpisah di `packaging\.buildenv`
2. Memasang dependensi runtime + `pyinstaller`
3. Memeriksa versi interpreter
4. Membuat ulang `packaging\obs-overlay.ico` dari kode ikon
5. Menjalankan PyInstaller dengan `packaging\ObsOverlay.spec`
6. Smoke test: menjalankan .exe hasil build sekali

Opsi:

```powershell
packaging\build.ps1 -Clean      # hapus output dan venv build dulu
packaging\build.ps1 -SkipVenv   # pakai interpreter yang sedang aktif
```

---

## Versi Python

Bangunlah dengan **Python 3.12** (paling aman) atau **3.13**. Jendelanya sempit:

| Paket | Batasan |
|---|---|
| `SpoutGL` 0.1.1 | wheel hanya sampai **cp313**; tidak ada 3.14, sdist tidak bisa dibangun di mesin bersih |
| `numpy` 2.5.x | butuh ≥ 3.12 |
| `PyQt6` 6.11 | butuh ≥ 3.10 |

> Jangan menulis `python-version: '3.x'` di CI — nilai itu akan diam-diam melompat ke
> versi terbaru dan membuat instalasi SpoutGL gagal. Workflow di repo ini mem-pin `3.12`.

---

## Kenapa venv terpisah

PyInstaller versi ≥ 6.5 **membatalkan build** kalau hook untuk lebih dari satu binding Qt
ikut berjalan (`ensure_single_qt_bindings_package`). Kalau `PyQt5` atau `PySide6` ada di
environment — bahkan hanya sebagai dependensi transitif dari `matplotlib` atau `qtpy` —
build gagal. Venv bersih menghilangkan seluruh kelas masalah ini.

Spec-nya juga mencantumkan binding lain di `excludes` sebagai lapis kedua.

---

## Keputusan di dalam spec

### one-dir, bukan one-file

One-file mengekstrak ~150 MB Qt + Python ke `%TEMP%` **setiap kali dijalankan**. Efeknya:
start dingin beberapa detik, antivirus memindai ulang setiap DLL, dan ini penyebab utama
false positive Defender/SmartScreen.

Kalau ingin satu berkas unduhan, bungkus folder one-dir dengan installer
(Inno Setup atau WiX) — bukan dengan `--onefile`.

### `upx=False`

PyInstaller otomatis melewati UPX untuk DLL ber-CFG dan plugin Qt, tapi **tidak** untuk
`Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`, atau `VCRUNTIME140.dll`. DLL inti Qt yang
dikompres UPX punya sejarah panjang crash diam-diam, dan pengepakan UPX sendiri adalah
salah satu heuristik antivirus terkuat.

### Tidak ada `collect_all('PyQt6')`

Hook per-modul bawaan PyInstaller sudah mengumpulkan yang dibutuhkan: plugin platform
(`qwindows.dll`), `imageformats`, `iconengines`, dan `styles`. `collect_all` justru
menyeret `QtWebEngineCore` beserta resource dan localenya — sekitar 250 MB percuma.

### Tidak ada manifest DPI

Qt 6 memanggil `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` sendiri. Manifest
tertanam yang menyatakan `dpiAware` membuat panggilan Qt gagal dengan `ERROR_ACCESS_DENIED`
dan aplikasi diam-diam turun ke *system aware* — hasilnya overlay buram di monitor kedua
dengan skala berbeda.

### Hidden imports

```python
"SpoutGL", "SpoutGL.enums", "SpoutGL.helpers",   # submodul di dalam C extension
"win32timezone",                                  # tidak dicakup hook mana pun
```

`SpoutGL/__init__.py` isinya hanya `from ._spoutgl import *`, dan `enums`/`helpers` adalah
submodul **dari extension C**-nya, jadi analisis statis tidak bisa melihatnya.

`win32timezone` gagal saat **runtime**, bukan saat build — tepatnya saat pywin32 pertama
kali mengonversi `datetime`.

### Spout.dll

Berkas nativenya bernama **`Spout.dll`** — bukan `SpoutLibrary.dll`, yang merupakan
artefak berbeda dari SDK C++. `_spoutgl.<abi>.pyd` menautkannya secara implisit, jadi DLL
itu harus berada di direktori yang sama.

`collect_dynamic_libs("SpoutGL")` dibiarkan dengan `destdir=None` (bawaan), yang
mempertahankan hierarki relatif paket sehingga hasilnya `_internal/SpoutGL/Spout.dll`.
Memaksa `destdir='.'` akan menaruhnya di akar bundle, tempat yang tidak diperiksa oleh
pencarian DLL milik extension itu sendiri.

---

## Antivirus melaporkan false positive

Bootloader PyInstaller adalah komponen bersama di setiap sampel malware buatan
PyInstaller, jadi heuristik Defender memang mengincarnya. Mitigasi, dari yang paling
efektif:

1. **Tanda tangani exe** dengan sertifikat Authenticode (EV atau OV).
2. Pakai **one-dir**, bukan one-file.
3. **Jangan pakai UPX.**
4. Isi **VS_VERSION_INFO** selengkapnya (sudah dilakukan di `packaging/version_info.txt`).
   Binary tanpa tanda tangan *dan* tanpa resource versi mendapat skor jauh lebih buruk.
5. Bangun ulang bootloader dari sumber supaya sidik byte-nya berbeda dari yang dikirim
   pip.
6. Laporkan false positive ke portal Microsoft Security Intelligence setelah tiap rilis.

---

## Ikon

```powershell
python packaging\make_icon.py
```

Menghasilkan `.ico` sembilan resolusi (16 – 256 px), setiap entri di-encode PNG.
Setiap ukuran dirender pada skalanya sendiri, bukan hasil perkecilan dari 256 px, supaya
geometri di `ui/icons.py` tetap tajam di slot tray 16 px.

Ikonnya digambar dalam kode, jadi tidak ada aset biner yang perlu disinkronkan dengan
tema.

---

## CI

`.github/workflows/ci.yml` menjalankan:

| Job | Di mana | Isi |
|---|---|---|
| **lint** | Ubuntu | ruff check, ruff format --check, mypy |
| **test** | Ubuntu (3.9–3.13) + Windows (3.12) | pytest dengan coverage; `mypy --platform win32` di Windows |
| **build** | Windows | PyInstaller + smoke test + upload artifact |
| **release** | Windows | Dijalankan pada tag `v*`; melampirkan zip ke GitHub Release |

Merilis versi baru:

```powershell
git tag v1.0.0
git push origin v1.0.0
```
