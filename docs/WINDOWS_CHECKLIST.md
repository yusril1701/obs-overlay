# Checklist verifikasi di Windows

Seluruh pengembangan sampai sekarang dilakukan di Linux tanpa GPU. 381 tes
otomatis lulus, tetapi **tes itu tidak bisa menyentuh apa pun yang butuh
Windows sungguhan**: Spout, NDI, Win32, dan installer.

Halaman ini adalah daftar yang harus dicoba manual, diurutkan dari yang paling
penting. Setiap butir menyebut: cara menjalankan, hasil yang benar, dan apa
artinya kalau gagal.

Beri tanda ✅/❌ sambil jalan — hasilnya berguna untuk agent AI di sesi
berikutnya.

---

## 0 — Persiapan

```powershell
git clone https://github.com/yusril1701/obs-overlay.git
cd obs-overlay
git checkout claude/vibrant-euler-pbqdhb

python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

ruff check src tests
ruff format --check src tests
mypy
mypy --platform win32
pytest -q
```

**Benar:** semuanya lulus, 381 tes.
**Kalau gagal:** kemungkinan besar versi Python. Harus 3.9–3.13; `SpoutGL`
tidak punya wheel di atas 3.13.

> `mypy --platform win32` baru benar-benar memeriksa cabang `native/` yang di
> Linux hanya berupa stub. Jangan dilewati.

---

## 1 — Aplikasi hidup tanpa OBS

```powershell
python -m obs_overlay --demo
```

| Yang diperiksa | Benar kalau |
|---|---|
| Overlay muncul | Pola animasi tampil di atas semua jendela |
| Transparansi | Area kosong benar-benar tembus pandang, bukan hitam/abu |
| Panel kontrol | Jendela terpisah terbuka, punya entri taskbar sendiri |
| Tray | Ikon muncul di system tray, menunya lengkap |

**Kalau overlay hitam pekat:** ini masalah alpha per-piksel Qt — periksa apakah
ada kode yang memanggil `SetLayeredWindowAttributes` atau menghapus
`WS_EX_LAYERED`. Lihat invarian di `CLAUDE.md`.

---

## 2 — Tembus klik (paling penting)

Ini inti seluruh aplikasi dan **belum pernah diuji sekali pun**.

1. Jalankan `--demo`, buka Notepad di belakang overlay.
2. Pastikan **Click through the overlay** aktif (tab Behaviour).
3. Klik di **area kosong** antara parsel.

| Yang diperiksa | Benar kalau |
|---|---|
| Klik di area kosong | Masuk ke Notepad, bukan ke overlay |
| Klik di dalam parsel | Juga tembus (karena `WS_EX_TRANSPARENT` berlaku untuk seluruh jendela) |
| Matikan click-through | Klik di dalam parsel tidak lagi tembus; di area kosong tetap tembus |

Baris terakhir itu yang membuktikan **hit-testing per-piksel** bekerja: dengan
click-through mati, lubang di antara parsel tetap tembus karena alpha-nya nol.
Kalau seluruh kotak jendela jadi solid, jalur raster tidak aktif.

4. Aktifkan **Never take keyboard focus**, klik overlay saat main game/Notepad
   → fokus keyboard **tidak** boleh pindah.

---

## 3 — Hotkey global

Default ada di `docs/HOTKEYS.md`. Coba satu per satu, dari aplikasi lain yang
sedang fokus:

| Hotkey | Harus |
|---|---|
| `Ctrl+Alt+M` | Masuk/keluar mode editor |
| `Ctrl+Alt+C` | Toggle click-through |
| `Ctrl+Alt+H` | Sembunyikan/tampilkan overlay |
| `Ctrl+Alt+P` | Buka/tutup panel |
| `Ctrl+Alt+R` | Muat ulang profil |
| `Ctrl+Alt+Shift+F9` | **Panic** — pulihkan click-through, tampilkan overlay, keluar editor, buka panel |

Lalu uji yang penting: **ganti flag jendela** (misalnya toggle *Hide from
taskbar*) dan coba hotkey lagi. Hotkey didaftarkan ke *thread*, bukan ke HWND,
justru supaya tetap hidup setelah Qt membuat ulang jendela nativenya. Kalau
mati setelah toggle, invarian itu rusak.

**Kalau sebuah hotkey tidak terdaftar:** alasannya muncul persis di bawah kolom
hotkey di tab Hotkeys. F12 memang ditolak — Windows memesannya untuk debugger.

---

## 4 — Perilaku jendela

| Setelan | Cara uji | Benar kalau |
|---|---|---|
| **Always on top** | Buka jendela lain, maksimalkan | Overlay tetap di atas |
| **Re-assert every** | Buka aplikasi fullscreen borderless | Overlay kembali ke atas dalam < 1 detik |
| **Hide from taskbar** | Lihat taskbar, tekan Alt+Tab | Overlay tidak muncul di keduanya |
| **Hide from screen capture** | Rekam layar dengan OBS/Game Bar | Overlay tidak terekam, **dan tidak jadi kotak hitam** |

Baris terakhir butuh Windows 10 build ≥ 19041 (`winver`). Di bawah itu aplikasi
**mengabaikan** permintaan dan mencatatnya di log — itu perilaku yang benar,
bukan bug. Kotak hitam pekat berarti Windows menurunkannya ke `WDA_MONITOR` dan
pemeriksaan build-nya bocor.

---

## 5 — Editor parsel

Mode editor: `Ctrl+Alt+M`.

| Aksi | Benar kalau |
|---|---|
| Drag parsel | Ikut mouse, snapping ke grid/parsel/tepi layar dengan garis bantu |
| Drag 8 pegangan | Ubah ukuran; `Shift` kunci rasio, `Alt` ubah dari tengah |
| Drag di area kosong | Parsel baru terbentuk |
| Rubber band / `Ctrl`+klik | Multi-select, lalu align & spread bekerja |
| `Ctrl+Z` / `Ctrl+Y` | Undo/redo sampai 64 langkah |
| Panah / `Shift`+panah | Geser 1 px / selangkah grid |
| Tabel di tab Parcels | Angka berubah seiring drag, dan sebaliknya |
| **Duplicate** | Salinan muncul dengan id baru, tidak menimpa aslinya |
| **Grid layout…** | Membuat kisi N×M sekaligus |
| Mode `Cut` | Melubangi parsel yang ada di atasnya dalam daftar |

Ubah beberapa parsel, tutup aplikasi, buka lagi → semuanya harus kembali persis
(penyimpanan atomik dengan debounce 1 detik).

---

## 6 — Pengaman

1. Buat parsel yang menutupi ≥ 92% layar.
2. Matikan click-through, opacity ≥ 50%.

**Benar:** aplikasi menyalakan kembali click-through sendiri dan memberi tahu
lewat notifikasi tray. Kalau tidak, Anda benar-benar tidak bisa mengklik apa pun
— termasuk ikon tray untuk memperbaikinya. Tekan `Ctrl+Alt+Shift+F9`.

---

## 7 — OBS lewat Spout2 (jalur utama, belum pernah dijalankan)

Persiapan lengkap: `docs/OBS_SETUP.md`. Ringkasnya:

1. Pasang [plugin Spout2](https://github.com/Off-World-Live/obs-spout2-plugin) 1.12+.
2. OBS → `Settings → Advanced → Video → Color Format` = **BGRA (8-bit)**.
   Ini penyebab nomor satu overlay jadi opaque — NV12 tidak punya alpha.
3. Tambahkan **Spout Filter** pada *scene* (bukan `Tools → Spout Output`; jalur
   Tools mengambil main mix yang NV12).
4. Tekan tombol **Change Spout Filter Name** — mengetik saja tidak cukup,
   propertinya memakai `OBS_PROPERTIES_DEFER_UPDATE`.
5. `Tools → Spout Output Settings` → centang **Continuous filter broadcast**.

```powershell
python -m obs_overlay --list-senders
```

| Yang diperiksa | Benar kalau |
|---|---|
| Sender terdaftar | Namanya muncul |
| Overlay tersambung | Status `Connected`, resolusi benar, FPS mendekati FPS OBS |
| Alpha | Bagian transparan di OBS benar-benar tembus di overlay |
| **Tepi antialias** | Tepi teks/lingkaran **bersih** — tidak bergaris gelap, tidak pucat |
| Ganti resolusi di OBS saat jalan | Overlay ikut, tanpa crash |
| Tutup OBS lalu buka lagi | Overlay menyambung ulang sendiri |

**Tepi bergaris gelap** = setelan premultiplied alpha salah. Untuk OBS harus
**aktif** (itu bawaannya). Kalau bawaan sudah aktif tapi tepinya tetap gelap,
asumsi di `docs/ARCHITECTURE.md` (Keputusan 2) perlu ditinjau ulang — catat
temuannya.

**Selalu "Waiting for a Spout sender"** padahal nama benar: kemungkinan besar
OBS dan overlay jalan di GPU berbeda (laptop hybrid). Spout tidak bisa berbagi
texture antar GPU. `Settings → System → Display → Graphics` → set `obs64.exe`
dan `ObsOverlay.exe` ke **High performance**, restart keduanya.

---

## 8 — NDI (belum pernah dijalankan sama sekali)

```powershell
pip install ndi-python
```

Lalu pasang **NDI Runtime** dari <https://ndi.video/> — terpisah karena
lisensinya. Butuh Python 3.10+.

```powershell
python -m obs_overlay --list-senders --source ndi
```

| Yang diperiksa | Benar kalau |
|---|---|
| Impor berhasil | Tab About menunjukkan NDI tersedia |
| Scan menemukan sumber | Nama `MESIN (Output)` muncul |
| Video masuk | Status `Connected`, gambar bergerak |
| Alpha | Sumber ber-alpha tampil benar dengan premultiplied **mati** |
| Sumber opaque | **Tidak hilang/berkedip** — ini uji jalur `BGRX` |
| Low bandwidth | Resolusi turun, trafik jauh berkurang |

Baris "sumber opaque" adalah yang paling penting. Pada frame `BGRX` byte keempat
adalah padding, bukan alpha, dan isinya tidak dijamin `0xFF`; kode memaksanya ke
255. Kalau sumber opaque justru menghilang, penanganan FourCC salah.

`ndi_source.py` ditulis dari API resmi dan contoh-contohnya tetapi **tidak
pernah dieksekusi**. Docstring-nya menyatakan itu terang-terangan. Anggap uji
pertama di mesin Anda sebagai uji yang sebenarnya.

---

## 9 — Tangkapan layar dan gambar

```powershell
python -m obs_overlay --list-senders --source screen
python -m obs_overlay --source screen --capture-monitor 1
python -m obs_overlay --image C:\path\logo.png
```

| Yang diperiksa | Benar kalau |
|---|---|
| Daftar monitor | Cocok dengan monitor yang benar-benar tersambung |
| Tangkap monitor lain | Isinya benar, tidak ada lag parah |
| Region | Koordinat relatif terhadap **monitor yang dipilih**, bukan virtual desktop |
| **Terowongan tak hingga** | Arahkan tangkapan ke monitor tempat overlay berada → capture exclusion menyala otomatis dan efek terowongan **tidak** terjadi |
| Monitor dicabut saat jalan | Status berbunyi `Monitor N is not connected`, tidak crash |
| PNG transparan | Alpha-nya utuh |
| GIF animasi | Berputar; mematikan **Play animation** menampilkan frame pertama saja |

Butir "terowongan" adalah satu-satunya fitur baru yang logikanya bergantung pada
Win32 dan belum pernah diuji sungguhan.

---

## 10 — Multi-monitor dan DPI

| Yang diperiksa | Benar kalau |
|---|---|
| `Covers = Specific monitor` | Overlay pindah ke monitor itu |
| `Covers = All monitors` | Menutupi virtual desktop penuh |
| Monitor dengan skala berbeda (100% + 150%) | Overlay **tajam** di keduanya |
| Cabut monitor saat overlay ada di sana | Kembali ke monitor utama, tidak crash |

Overlay buram di monitor kedua berarti aplikasi turun ke *system DPI aware*.
Penyebabnya hampir pasti sebuah manifest DPI yang tertanam — spec PyInstaller
sengaja tidak memasangnya, karena Qt 6 memanggil
`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` sendiri dan manifest
membuat panggilan itu gagal.

---

## 11 — Build dan installer

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Clean -Installer
```

Butuh [Inno Setup 6](https://jrsoftware.org/isdl.php)
(`winget install JRSoftware.InnoSetup`).

Hasil:
- `packaging\dist\ObsOverlay\ObsOverlay.exe` (portable)
- `packaging\installer\ObsOverlay-1.1.0-setup.exe`

> CI sudah membangun keduanya dan lulus smoke test. Kalau tidak mau membangun
> sendiri, unduh dari tab **Actions** → run terbaru → **Artifacts**.

Uji installer-nya:

| Langkah | Benar kalau |
|---|---|
| Jalankan setup | **Tidak** meminta administrator (bawaannya per-pengguna) |
| SmartScheen muncul | Wajar — belum ditandatangani. *More info → Run anyway* |
| Selesai | Pintasan Start Menu ada, termasuk varian *(test pattern)* |
| Apps & features | Entri "OBS Overlay 1.1.0" muncul |
| Jalankan dari Start Menu | Aplikasi hidup, tidak ada error path |
| Centang autostart saat install | Sign out & masuk lagi → aplikasi jalan sendiri |
| Buat beberapa profil | Tersimpan di `%APPDATA%\obs-overlay` |
| Pasang ulang installer yang sama | Menimpa versi lama (bukan terpasang berdampingan), **profil tetap ada** |
| Uninstall | Bertanya soal profil; jawab **No** → folder `%APPDATA%` tetap utuh |
| Uninstall lalu jawab **Yes** | `%APPDATA%\obs-overlay` terhapus |
| Setelah uninstall | `C:\Program Files\OBS Overlay` bersih, tidak ada sisa |

Uji juga mode portable: ekstrak zip, buat berkas kosong `portable.txt` di
sebelah `ObsOverlay.exe` → semua data masuk ke subfolder `data\` di situ.
**Salinan hasil installer tidak boleh punya `portable.txt`** — kalau punya,
aplikasi akan mencoba menulis profil ke Program Files dan gagal.

---

## 12 — Kondisi yang belum terpecahkan

Di QPA headless (`offscreen`/`minimal`) di Linux, `app.exec()` kadang tidak
kembali saat shutdown bila overlay terlihat dan feed hidup. Sekitar 6 dari 8
percobaan bersih. Dump stack menunjukkan producer tidur normal dan main thread
di dalam `app.exec()` tanpa frame Python — tidak ada kode aplikasi yang
memblokir.

**Di Windows, periksa ini:** tutup aplikasi (tombol X, menu tray → Quit, dan
hotkey panic lalu Quit) sebanyak 10 kali, dengan feed aktif dan overlay
terlihat. Pastikan prosesnya benar-benar hilang dari Task Manager setiap kali.

Kalau di Windows **tidak pernah** terjadi, kemungkinan besar ini artefak
platform offscreen dan bisa ditutup. Kalau **terjadi**, itu temuan baru dan
penting — catat langkah reproduksinya.

---

## Melaporkan hasil

Untuk agent AI di sesi berikutnya, yang paling berguna:

1. Butir mana yang ❌, dan pesan galat persisnya.
2. `%APPDATA%\obs-overlay\logs\obs-overlay.log` setelah dijalankan dengan
   `--log-level DEBUG`.
3. Versi Windows (`winver`), versi OBS, versi plugin Spout2.
4. Profil Anda (tab Profiles → **Export**) — JSON biasa, aman dibagikan.
