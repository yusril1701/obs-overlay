# OBS Overlay

**Overlay transparan dan tembus-klik untuk Windows, menerima video dari OBS Studio lewat Spout2.**

Aplikasi ini menampilkan hasil render OBS di atas seluruh layar (*always on top*) dengan
transparansi penuh (*alpha channel*), lalu **memotong jendelanya menjadi kotak-kotak
(parsel)**. Area di antara kotak bukan cuma transparan secara visual — area itu benar-benar
tidak ada, sehingga klik mouse tembus ke aplikasi di belakangnya.

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
| Windows | 10 atau 11 (64-bit) | API Win32 dan Spout wajib Windows |
| Python | 3.9 – 3.13 | `SpoutGL` tidak punya wheel di atas 3.13 |
| OBS Studio | 30 / 31 / 32 | |
| Plugin Spout2 untuk OBS | 1.12.0+ | [Off-World-Live/obs-spout2-plugin](https://github.com/Off-World-Live/obs-spout2-plugin) |
| GPU | satu GPU saja | Spout tidak bisa berbagi antar GPU — lihat [Kalau ada masalah](#kalau-ada-masalah) |

> **Catatan:** aplikasi ini juga bisa dijalankan di Linux/macOS untuk pengembangan dan
> pengujian (dengan sumber uji bawaan), tetapi *click-through*, hotkey global, dan Spout
> hanya aktif di Windows.

---

## Instalasi cepat

### Opsi A — file .exe siap pakai

Unduh `ObsOverlay-<versi>-windows-x64.zip` dari halaman
[Releases](https://github.com/yusril1701/obs-overlay/releases), ekstrak, lalu jalankan
`ObsOverlay.exe`. Tidak perlu memasang Python.

### Opsi B — dari kode sumber

```powershell
git clone https://github.com/yusril1701/obs-overlay.git
cd obs-overlay

python -m venv .venv
.venv\Scripts\activate

pip install -e .
obs-overlay
```

Mau mencoba dulu tanpa OBS? Jalankan dengan pola uji bawaan:

```powershell
obs-overlay --demo
```

Panel kontrol akan terbuka dan overlay langsung tampil dengan pola animasi yang punya
area transparan sungguhan — bagus untuk memastikan alpha bekerja sebelum menyentuh OBS.

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

  -p, --profile NAMA     Muat profil tertentu
      --demo             Paksa pakai pola uji bawaan
      --sender NAMA      Timpa nama Spout sender untuk sesi ini
      --monitor INDEKS   Taruh overlay di monitor ini (0 = pertama)
      --edit             Langsung masuk mode editor
      --no-panel         Jangan buka panel kontrol saat mulai
      --log-level LEVEL  DEBUG / INFO / WARNING / ERROR / CRITICAL
      --data-dir PATH    Pakai folder lain untuk profil dan log
      --list-senders     Tampilkan Spout sender yang aktif, lalu keluar
      --list-profiles    Tampilkan profil tersimpan, lalu keluar
      --version          Tampilkan versi
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

pytest                    # 300+ tes, jalan tanpa GPU/OBS
ruff check src tests
ruff format src tests
mypy
```

Arsitektur, alasan di balik keputusan teknis (kenapa raster dan bukan OpenGL, kenapa
alpha premultiplied, bagaimana buffer pool bekerja) dijelaskan di
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

Dokumen lain:

- [docs/OBS_SETUP.md](docs/OBS_SETUP.md) — panduan OBS langkah demi langkah
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — penjelasan tiap setelan
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — diagnosis masalah
- [docs/BUILD.md](docs/BUILD.md) — packaging
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
