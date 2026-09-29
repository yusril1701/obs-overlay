# OBS Overlay

**Overlay transparan dan tembus-klik untuk Windows — dari OBS Studio (Spout2), NDI,
tangkapan layar, atau berkas gambar.**

Aplikasi ini menampilkan video di atas seluruh layar (*always on top*) dengan transparansi
penuh (*alpha channel*), lalu **memotong jendelanya menjadi kotak-kotak (parsel)**. Area di
antara kotak bukan cuma transparan secara visual — area itu benar-benar tidak ada, sehingga
klik mouse tembus ke aplikasi di belakangnya.

| Sumber | Butuh apa | Alpha |
|---|---|---|
| **OBS via Spout2** | plugin Spout2 + `SpoutGL` | ya (premultiplied) |
| **NDI** | `ndi-python` + NDI Runtime | ya (straight) |
| **Tangkapan layar** | — | tidak (opaque) |
| **Berkas gambar** | — | ya (PNG/GIF/WebP) |
| **Pola uji bawaan** | — | ya |

Dibangun dari *Project Blueprint: OBS Spout to Python Transparent Overlay*, lengkap sampai
Fase 4 (editor parsel interaktif).

```
┌─────────────────────────────────────────────┐
│  OBS Studio                                 │
│  Scene dengan background transparan         │
│         │                                   │
│         ▼  filter "Spout Filter"            │
│  ┌───────────────┐                          │
│  │ texture GPU   │ ──── shared memory ────┐ │
│  └───────────────┘   (tanpa latensi)      │ │
└───────────────────────────────────────────┼─┘
                                            ▼
┌─────────────────────────────────────────────┐
│  OBS Overlay (aplikasi ini)                 │
│                                             │
│   SpoutGL ──► buffer pool ──► QImage        │
│                    │                        │
│                    ▼                        │
│   ┌──────────┐        ┌──────────┐          │
│   │ Parsel 1 │        │ Parsel 2 │  ◄── hanya di sini video terlihat
│   └──────────┘        └──────────┘          │
│        ▲ di luar kotak: tembus pandang      │
│          DAN tembus klik                    │
└─────────────────────────────────────────────┘
```

---

## Daftar isi

- [Fitur](#fitur)
- [Persyaratan](#persyaratan)
- [Instalasi cepat](#instalasi-cepat)
- [Memilih sumber video](#memilih-sumber-video)
- [Menyiapkan OBS](#menyiapkan-obs)
- [Cara pakai](#cara-pakai)
- [Hotkey](#hotkey)
- [Baris perintah](#baris-perintah)
- [Membangun file .exe](#membangun-file-exe)
- [Kalau ada masalah](#kalau-ada-masalah)
- [Untuk pengembang](#untuk-pengembang)
- [Lisensi](#lisensi)
- [English summary](#english-summary)

---

## Fitur

**Inti (sesuai blueprint)**

- Jendela *frameless*, *always on top*, dengan alpha per-piksel yang sebenarnya.
- *Click-through* (ghosting) lewat `WS_EX_TRANSPARENT` — mouse tembus ke bawah.
- *Window masking* dengan `setMask(QRegion)`: video tidak diubah ukurannya, ia hanya
  "terlihat" lewat lubang-lubang yang Anda tentukan.
- Penerima Spout2 real-time 60 FPS lewat `SpoutGL`.
- Tidak muncul di taskbar maupun Alt-Tab, dan tidak pernah mencuri fokus keyboard.

**Di atas blueprint**

- **Empat sumber video selain OBS** — NDI lewat jaringan, tangkapan layar (satu monitor
  atau sebagian saja), berkas gambar PNG/GIF/WebP dengan alpha, dan pola uji bawaan.
  Setiap sumber punya setelannya sendiri dan semuanya disimpan, jadi berpindah sumber
  tidak menghapus konfigurasi yang lain.
- **Editor parsel interaktif** — geser, ubah ukuran, dan bentuk kotak langsung di layar,
  dengan *snapping*, garis bantu, *multi-select*, *align/distribute*, dan undo/redo 64 langkah.
- **Empat bentuk parsel**: persegi, persegi sudut tumpul, elips, dan poligon.
- **Mode "Cut"** — parsel bisa *mengurangi* parsel di bawahnya, jadi Anda bisa membuat
  lubang di tengah kotak (donat, bingkai, dan sejenisnya).
- **Profil** — simpan beberapa tata letak lengkap dan berpindah di antaranya.
- **Panel kontrol** lengkap dengan pratinjau status koneksi, HUD statistik (FPS, frame
  drop, jitter, latensi), dan pemilih monitor.
- **Hotkey global** yang bisa diubah, dengan pesan jelas kalau kombinasinya sudah dipakai
  aplikasi lain.
- **Sumber uji bawaan** — tata letak bisa dikerjakan tanpa OBS atau Spout terpasang sama
  sekali.
- **Pengaman**: tata letak yang menutupi hampir seluruh layar tanpa click-through akan
  otomatis dikembalikan, plus hotkey *panic*. Anda tidak bisa terkunci di luar desktop
  sendiri.
- Penyimpanan profil **atomik** — mati listrik tidak merusak konfigurasi.
- **Menyembunyikan diri dari screen capture** (opsional), supaya overlay tidak terekam
  balik oleh OBS saat Anda meng-capture layar yang sama.

---

## Persyaratan

| Komponen | Versi | Catatan |
|---|---|---|
| Windows | 10 atau 11 (64-bit) | API Win32 wajib Windows |
| Python | 3.9 – 3.13 | `SpoutGL` tidak punya wheel di atas 3.13 |

Hanya dibutuhkan kalau Anda memakai sumber yang bersangkutan:

| Sumber | Yang perlu dipasang |
|---|---|
| **OBS / Spout2** | OBS Studio 30–32, [plugin Spout2](https://github.com/Off-World-Live/obs-spout2-plugin) 1.12+, `pip install SpoutGL`. Satu GPU saja — lihat [Kalau ada masalah](#kalau-ada-masalah). |
| **NDI** | `pip install ndi-python` **dan** NDI Runtime dari [ndi.video](https://ndi.video/) (dipasang terpisah karena lisensinya). Butuh Python 3.10+. |
| **Layar / gambar / pola uji** | Tidak ada — cukup Qt. |

> **Catatan:** aplikasi ini juga bisa dijalankan di Linux/macOS untuk pengembangan dan
> pengujian (dengan sumber uji bawaan), tetapi *click-through*, hotkey global, dan Spout
> hanya aktif di Windows.

---

## Instalasi cepat

### Opsi A — installer (paling mudah)

Unduh `ObsOverlay-<versi>-setup.exe` dari halaman
[Releases](https://github.com/yusril1701/obs-overlay/releases) dan jalankan. Tidak perlu
memasang Python, dan tidak perlu hak administrator — bawaannya memasang untuk pengguna
Anda saja, meski dialognya tetap menawarkan pemasangan untuk semua pengguna.

Yang dilakukan installer: pintasan Start Menu (plus desktop dan autostart kalau dicentang),
entri di **Apps & features**, dan uninstaller. Profil Anda disimpan di
`%APPDATA%\obs-overlay` dan **tidak** ikut terhapus saat uninstall kecuali Anda
menjawab ya waktu ditanya.

> Windows SmartScreen akan memperingatkan karena berkasnya belum ditandatangani secara
> digital. **More info → Run anyway.** Ini berlaku untuk semua aplikasi open-source tanpa
> sertifikat Authenticode, yang harganya ratusan dolar per tahun.

### Opsi B — portable (flash disk)

Unduh `ObsOverlay-<versi>-windows-x64.zip`, ekstrak, jalankan `ObsOverlay.exe`. Tidak
mengubah apa pun di sistem. Untuk menyimpan profil di dalam foldernya sendiri — cocok
untuk flash disk — buat berkas kosong bernama `portable.txt` di sebelah `ObsOverlay.exe`.

### Opsi C — dari kode sumber

```powershell
git clone https://github.com/yusril1701/obs-overlay.git
cd obs-overlay

python -m venv .venv
.venv\Scripts\activate

pip install -e .
obs-overlay
```

Mau memakai NDI? Tambahkan ekstranya (Runtime-nya tetap dipasang terpisah):

```powershell
pip install -e ".[ndi]"
```

Mau mencoba dulu tanpa OBS? Jalankan dengan pola uji bawaan:

```powershell
obs-overlay --demo
```

Panel kontrol akan terbuka dan overlay langsung tampil dengan pola animasi yang punya
area transparan sungguhan — bagus untuk memastikan alpha bekerja sebelum menyentuh OBS.

---

## Memilih sumber video

Tab **Source** di panel kontrol. Setiap sumber menampilkan setelannya sendiri; setelan
sumber lain tetap tersimpan.

### OBS via Spout2
Pilihan utama, satu-satunya yang membawa alpha langsung dari komposisi OBS.
Lihat [Menyiapkan OBS](#menyiapkan-obs).

### NDI
Untuk menerima dari mesin lain di jaringan, atau dari aplikasi yang mengirim NDI.

```powershell
pip install ndi-python
```

Lalu pasang **NDI Runtime** dari [ndi.video](https://ndi.video/) — ini terpisah karena
lisensinya. Tekan **Scan** untuk mencari sumber di jaringan.

> NDI mengirim alpha **straight**, kebalikan dari OBS/Spout. Setelan "Source uses
> premultiplied alpha" karena itu **mati** secara bawaan untuk NDI.

### Tangkapan layar
Menangkap satu monitor, atau sebagian saja (centang **Capture only part of the monitor**
lalu isi X/Y/W/H relatif terhadap monitor tersebut).

> **Jangan menangkap monitor yang ditempati overlay** — overlay akan memotret dirinya
> sendiri dan menghasilkan efek terowongan tak terhingga. Aplikasi mendeteksi ini dan
> otomatis menyembunyikan overlay dari tangkapan layar (butuh Windows 10 versi 2004+).
> Cara paling aman tetap: tangkap monitor yang berbeda.

Tangkapan layar tidak punya alpha — hasilnya selalu opaque di dalam parsel.

### Berkas gambar
Cara tercepat menaruh logo atau bingkai di layar: pilih PNG dengan transparansi. GIF dan
WebP animasi juga bisa diputar.

Gambar diam hanya dikirim **sekali** lalu pipeline menganggur sepenuhnya — overlay
menyimpan frame terakhir, jadi tidak ada CPU yang terbuang.

### Pola uji bawaan
Pola animasi dengan area transparan sungguhan. Untuk menata parsel sebelum OBS jalan, dan
untuk memastikan jalur alpha bekerja.

---

## Menyiapkan OBS

Ini bagian yang paling sering salah, jadi ikuti urutannya. Panduan lengkap dengan
penjelasan tiap langkah ada di **[docs/OBS_SETUP.md](docs/OBS_SETUP.md)**.

1. **Pasang plugin Spout2**, lalu **restart OBS**.

2. **Setel format warna ke BGRA.**
   `Settings → Advanced → Video → Color Format` → pilih **BGRA (8-bit)**.

   > Tanpa langkah ini feed tidak punya alpha channel sama sekali dan overlay akan
   > tampil buram/hitam, bukan transparan.

3. **Tambahkan filter pada scene**, bukan output global.
   Klik kanan scene (atau source) → `Filters` → `+` → **Spout Filter**.

   > Jangan memakai `Tools → Spout Output`. Jalur itu mengambil main mix yang formatnya
   > NV12 — alphanya sudah hilang di sana.

4. **Beri nama sender, lalu tekan tombolnya.**
   Isi kolom nama, lalu **wajib klik tombol "Change Spout Filter Name"**.

   > Nama tidak berlaku sampai tombol itu ditekan — ini penyebab keluhan nomor satu
   > pengguna plugin tersebut. Nama bawaannya `Spout_OBS_Filter`.

5. **Aktifkan siaran terus-menerus.**
   `Tools → Spout Output Settings` → centang **Continuous filter broadcast**.

   > Kalau tidak dicentang, sender berhenti begitu Anda pindah scene.

6. **Pastikan background scene benar-benar transparan** — tidak ada Color Source atau
   gambar latar di bawahnya.

7. Kembali ke aplikasi ini: tab **Source** → **Refresh** → pilih sender Anda.

---

## Cara pakai

### Menata parsel

Tekan **`Ctrl+Alt+M`** (atau klik **Edit layout** di panel). Overlay berubah jadi kanvas
editor: mask dilepas, klik diterima lagi, dan seluruh frame ditampilkan redup supaya
Anda tahu bagian mana yang sedang dipotong.

| Aksi | Cara |
|---|---|
| Pilih | Klik parsel |
| Pilih banyak | `Shift` + klik, atau seret di area kosong |
| Pindah | Seret badan parsel |
| Ubah ukuran | Seret salah satu dari 8 pegangan |
| Jaga rasio | Tahan `Shift` saat mengubah ukuran |
| Ubah dari tengah | Tahan `Alt` saat mengubah ukuran |
| Buat parsel baru | `Ctrl` + seret di area kosong |
| Geser presisi | Tombol panah (1 px), `Shift`+panah (satu grid) |
| Duplikat | `Ctrl+D` |
| Hapus | `Delete` |
| Pilih semua | `Ctrl+A` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Urutan tumpukan | `Ctrl+[` / `Ctrl+]` |
| Menu lengkap | Klik kanan |
| Selesai | `Esc` |

Parsel otomatis *snap* ke grid, ke tepi dan tengah parsel lain, serta ke tepi dan tengah
layar. Semuanya bisa diatur di tab **Editor**.

### Membuat lubang di dalam kotak

Di tab **Parcels**, ubah kolom **Mode** sebuah parsel dari `Add` menjadi `Cut`. Parsel itu
akan *mengurangi* semua parsel yang ada di atasnya dalam daftar. Susunan daftar = urutan
tumpukan, jadi taruh parsel `Cut` **setelah** parsel yang ingin dilubangi.

### Profil

Satu profil menyimpan satu setup lengkap: sumber, penempatan, parsel, perilaku jendela,
dan hotkey. Buat satu profil per scene lalu pindah lewat tab **Profiles** atau menu tray.

Lokasi penyimpanan: `%APPDATA%\obs-overlay\profiles\`

---

## Hotkey

Semuanya global (berfungsi walau aplikasi lain sedang fokus) dan bisa diubah di tab
**Hotkeys**.

| Aksi | Default |
|---|---|
| Buka/tutup editor tata letak | `Ctrl+Alt+M` |
| Aktif/nonaktifkan click-through | `Ctrl+Alt+C` |
| Tampil/sembunyikan overlay | `Ctrl+Alt+H` |
| Tampil/sembunyikan panel kontrol | `Ctrl+Alt+P` |
| Muat ulang profil dari disk | `Ctrl+Alt+R` |
| **Panic** — kembalikan input, tampilkan panel | `Ctrl+Alt+Shift+F9` |

> **F12 tidak bisa dipakai.** Windows memesannya untuk debugger dan `RegisterHotKey`
> akan menolaknya. Aplikasi ini akan memberi tahu Anda kalau mencoba.

---

## Baris perintah

```
obs-overlay [OPSI]

  -p, --profile NAMA         Muat profil tertentu
      --source KIND          Paksa sumber: spout / ndi / screen / image / demo
      --demo                 Sama dengan --source demo
      --sender NAMA          Timpa nama sender (Spout, atau NDI dengan --source ndi)
      --image PATH           Tampilkan berkas gambar ini (menyiratkan --source image)
      --capture-monitor N    Monitor yang ditangkap dengan --source screen (0 = pertama)
      --monitor INDEKS       Taruh overlay di monitor ini (0 = pertama)
      --edit                 Langsung masuk mode editor
      --no-panel             Jangan buka panel kontrol saat mulai
      --log-level LEVEL      DEBUG / INFO / WARNING / ERROR / CRITICAL
      --data-dir PATH        Pakai folder lain untuk profil dan log
      --list-senders         Tampilkan yang bisa disambungkan, lalu keluar
                             (ikut --source: spout / ndi / screen)
      --list-profiles        Tampilkan profil tersimpan, lalu keluar
      --version              Tampilkan versi
```

Contoh:

```powershell
obs-overlay --list-senders --source ndi      # cari sumber NDI di jaringan
obs-overlay --list-senders --source screen   # daftar monitor yang tersambung
obs-overlay --source screen --capture-monitor 1
obs-overlay --image C:\logo.png
```

Penimpaan lewat baris perintah **tidak disimpan** — menjalankan `--demo` sekali tidak
akan mengubah profil Anda.

---

## Membangun file .exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

atau klik dua kali `packaging\build.bat`.

Hasilnya ada di `packaging\dist\ObsOverlay\`. Detail dan alasan tiap pilihan build ada di
**[docs/BUILD.md](docs/BUILD.md)**.

---

## Kalau ada masalah

Ringkasan masalah yang paling sering muncul. Daftar lengkap: **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**.

| Gejala | Penyebab paling mungkin |
|---|---|
| Overlay hitam/buram, tidak transparan | `Color Format` di OBS belum **BGRA (8-bit)** |
| Tepi gambar bergaris gelap | Setelan **premultiplied alpha** tidak cocok (tab Source) |
| Efek terowongan tak terhingga | Tangkapan layar diarahkan ke monitor yang ditempati overlay |
| NDI tidak menemukan sumber | NDI Runtime belum terpasang, atau mDNS diblokir firewall |
| Sender tidak muncul di daftar | Filter dipasang tapi tombol **Change Spout Filter Name** belum ditekan |
| Sender hilang saat ganti scene | **Continuous filter broadcast** belum dicentang |
| Selalu "Waiting for a Spout sender" | OBS dan aplikasi ini jalan di GPU berbeda (laptop hybrid) |
| Hotkey tidak berfungsi | Kombinasinya sudah dipakai aplikasi lain — alasannya muncul di tab Hotkeys |
| Overlay tertutup game fullscreen | Game *exclusive fullscreen* melewati DWM; pakai Borderless Windowed |

Log lengkap ada di `%APPDATA%\obs-overlay\logs\obs-overlay.log`
(tombol **Open data folder** ada di tab About).

---

## Untuk pengembang

```powershell
pip install -e ".[dev]"

pytest                    # 381 tes, jalan tanpa GPU/OBS
ruff check src tests
ruff format src tests
mypy
```

Arsitektur, alasan di balik keputusan teknis (kenapa raster dan bukan OpenGL, kenapa
alpha premultiplied, bagaimana buffer pool bekerja) dijelaskan di
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

Dokumen lain:

**Untuk pengguna**

- [docs/OBS_SETUP.md](docs/OBS_SETUP.md) — panduan OBS langkah demi langkah
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — penjelasan tiap setelan
- [docs/HOTKEYS.md](docs/HOTKEYS.md) — daftar dan perilaku hotkey
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — diagnosis masalah

**Untuk pengembang**

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — bagaimana dan **kenapa** kodenya begitu
- [docs/BUILD.md](docs/BUILD.md) — packaging dan installer
- [docs/WINDOWS_CHECKLIST.md](docs/WINDOWS_CHECKLIST.md) — verifikasi manual yang hanya
  bisa dilakukan di Windows; ini berisi semua yang belum pernah diuji di perangkat nyata
- [docs/ROADMAP.md](docs/ROADMAP.md) — yang bisa dikerjakan berikutnya, dan yang
  sebaiknya tidak
- [CLAUDE.md](CLAUDE.md) — instruksi untuk agent AI: invarian yang tidak boleh
  "diperbaiki", resep menambah sumber/setelan, dan status verifikasi
- [CONTRIBUTING.md](CONTRIBUTING.md) — cara berkontribusi
- [CHANGELOG.md](CHANGELOG.md) — riwayat perubahan

---

## Lisensi

[MIT](LICENSE).

---

## English summary

**OBS Overlay** is a Windows desktop overlay that receives a transparent video feed from
OBS Studio over Spout2 and paints it always-on-top with true per-pixel alpha. The window
is then physically cut into user-defined "parcels": the gaps between them are not merely
transparent, they are absent, so mouse input passes through to whatever is behind.

Beyond the original blueprint it adds an interactive on-screen parcel editor (drag,
resize, snap, align, undo/redo), four parcel shapes plus boolean subtraction, profiles,
global hotkeys, a debug HUD, a built-in test-pattern source so the whole app is usable
without OBS installed, and safety guards that make it impossible to trap your own mouse.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the engineering rationale, including
why the renderer uses Qt's raster backing store rather than OpenGL, and why the Spout feed
must be treated as premultiplied alpha.
