# Mengatasi masalah

Mulai dari log — hampir semua hal di halaman ini muncul di sana dengan jelas:

```
%APPDATA%\obs-overlay\logs\obs-overlay.log
```

Tombol **Open data folder** ada di tab **About**. Untuk log lebih rinci:

```powershell
obs-overlay --log-level DEBUG
```

---

## Overlay tidak transparan (hitam atau buram)

**1. Color Format OBS masih NV12.**
`Settings → Advanced → Video → Color Format` harus **BGRA (8-bit)**. NV12 tidak punya
alpha channel sama sekali, jadi tidak ada yang bisa diselamatkan di sisi penerima.
Ini penyebab nomor satu.

**2. Anda memakai `Tools → Spout Output`, bukan filter.**
Jalur Tools mengambil main mix OBS yang formatnya NV12. Pakai **Spout Filter** pada scene.

**3. Ada yang menggambar hitam di scene.**
Color Source, gambar latar, atau Browser Source dengan background sendiri. Preview OBS
akan menunjukkan hitam pekat, bukan kotak-kotak catur.

**4. Log mencatat format sender tanpa alpha.**
Cari baris seperti:

```
WARNING Sender format 88 carries no alpha channel — the overlay will be opaque.
```

Format 88 adalah `B8G8R8X8_UNORM` — huruf X berarti byte alpha diabaikan. Kembali ke
langkah 1.

---

## Tepi gambar bergaris gelap

Setelan **"…uses premultiplied alpha"** (tab Source) tidak cocok dengan sumbernya.

- Sender OBS → **harus aktif** (bawaan Spout).
- Sumber NDI → **harus nonaktif** (bawaan NDI; spesifikasinya menyatakan tidak premultiplied).
- Sumber straight-alpha lain (beberapa aplikasi VJ) → matikan.

Garis gelap = data premultiplied diperlakukan sebagai straight. Tepi pucat/terlalu terang
= kebalikannya.

---

## Sender tidak muncul di daftar

**1. Tombol "Change Spout Filter Name" belum ditekan.**
Mengetik nama saja tidak cukup — properti filter memakai `OBS_PROPERTIES_DEFER_UPDATE`.
Sampai tombol ditekan, sendernya masih bernama `Spout_OBS_Filter`.

**2. Scene-nya tidak sedang dirender.**
Tanpa **Continuous filter broadcast**, filter berhenti mengirim begitu Anda pindah scene.
`Tools → Spout Output Settings` → centang opsinya.

**3. Source berukuran nol.**
Browser Source yang masih memuat atau Media Source tanpa berkas membuat filter melewati
frame sepenuhnya. Sendernya terdaftar tapi tidak pernah mengirim apa-apa.

**4. Cold start.**
Kalau OBS dan overlay dijalankan bersamaan, inisialisasi DX11 filter bisa gagal di
beberapa frame pertama (`Failed to init DX11 for spout filter, will retry next frame`).
Overlay akan mencoba lagi otomatis.

Periksa dari baris perintah:

```powershell
obs-overlay --list-senders
```

---

## Selalu "Waiting for a Spout sender"

**GPU berbeda.** Ini penyebab paling sering kalau nama sendernya benar. Spout hanya bisa
berbagi texture di dalam satu GPU.

Di laptop hybrid, OBS bisa jalan di dGPU sementara overlay di iGPU.

```
Windows Settings → System → Display → Graphics
```

Tambahkan `obs64.exe` dan `ObsOverlay.exe` (atau `python.exe`), setel keduanya ke
**High performance**, lalu restart keduanya.

---

## `SpoutGL is not installed`

```powershell
pip install SpoutGL
```

Hanya tersedia untuk Windows. Wheel resmi ada untuk CPython **3.8 sampai 3.13** — tidak
ada untuk 3.14, dan sdist-nya tidak bisa dibangun di mesin bersih. Kalau `pip` mencoba
mengompilasi dari sumber, artinya versi Python Anda terlalu baru:

```powershell
python --version    # harus 3.9 - 3.13
```

---

## `DLL load failed while importing _spoutgl`

Terjadi pada build hasil PyInstaller kalau `Spout.dll` tidak ikut terbawa.

Periksa isi bundle:

```
packaging\dist\ObsOverlay\_internal\SpoutGL\Spout.dll
```

Berkasnya bernama **`Spout.dll`**, bukan `SpoutLibrary.dll` (itu artefak lain dari SDK
C++). Hook di `packaging/hooks/hook-SpoutGL.py` seharusnya menanganinya; kalau tidak,
bangun ulang dengan `-Clean`.

---

## `The NDI binding is not installed`

NDI butuh **dua** hal, dan keduanya dipasang terpisah:

```powershell
pip install ndi-python
```

lalu **NDI Runtime** dari <https://ndi.video/download-ndi-sdk/>. Runtime tidak boleh
dibundel ulang karena lisensinya, jadi paket Python saja tidak cukup — impornya akan
gagal mencari `Processing.NDI.Lib.x64.dll`.

Periksa keduanya dari baris perintah:

```powershell
obs-overlay --list-senders --source ndi
```

---

## Sumber NDI tidak ditemukan

**1. Beri waktu.** NDI menemukan sumber lewat mDNS, dan pemindaian pertama butuh beberapa
detik. Tombol **Scan** bisa perlu ditekan dua kali pada jaringan yang lambat.

**2. mDNS diblokir.** Ini penyebab paling sering. NDI memakai multicast UDP port 5353;
Wi-Fi tamu, VLAN terpisah, dan sebagian besar VPN memblokirnya. Sumber di subnet lain
tidak akan pernah muncul tanpa NDI Discovery Server.

**3. Firewall Windows.** Izinkan aplikasi pada profil **Private**. Kalau jaringannya
terdeteksi sebagai Public, Windows membuang paket discovery tanpa memberi tahu.

**4. Nama salah ketik.** Nama NDI berbentuk `NAMAKOMPUTER (Nama Output)`, termasuk
kurungnya. Lebih aman pilih dari daftar hasil **Scan** daripada mengetiknya.

Kalau sumbernya ada tapi gambarnya tidak pernah datang, naikkan
`--log-level DEBUG` dan perhatikan apakah frame yang diterima bertipe audio atau metadata
saja — itu berarti pengirimnya belum mengirim video.

---

## Tangkapan layar jadi terowongan tak hingga

Overlay berada di monitor yang sedang ditangkap, jadi ia memotret dirinya sendiri.

Aktifkan **Hide the overlay from its own capture** (tab Source → Screen capture). Aplikasi
akan menyalakan capture exclusion otomatis begitu area tangkap dan jendela overlay
bersinggungan.

Butuh Windows 10 versi 2004 (build 19041) ke atas. Di bawah itu:

- pindahkan overlay ke monitor lain (tab Display → **Covers**), atau
- tangkap sebuah **region** yang tidak bersinggungan dengan overlay.

---

## Tangkapan layar hitam atau kosong

**1. Yang ditangkap memakai protected content.** Netflix, Spotify, dan sebagian pemutar
DRM sengaja tampil hitam pada tangkapan layar apa pun. Ini bukan bug aplikasi ini.

**2. Monitor sudah dicabut.** Status di bagian Connection akan berbunyi
`Monitor N is not connected`. Pilih monitor lain; daftarnya menyesuaikan sendiri.

**3. Region-nya di luar monitor.** Koordinat region relatif terhadap sudut kiri-atas
monitor yang dipilih, bukan virtual desktop. Region `X=3000` pada monitor 1920 piksel
tidak menangkap apa pun.

**4. Tangkapan layar tidak punya alpha.** Ini normal — hasilnya selalu opaque. Untuk
membuat sebagian tembus pandang, pakai parsel (tab Parcels), bukan alpha sumber.

---

## Berkas gambar tidak muncul

Status di bagian Connection menyebutkan alasannya secara persis:

| Pesan | Artinya |
|---|---|
| `Image not found: …` | Path-nya salah, atau berkasnya dipindah |
| `No image file has been chosen.` | Kolom **Image file** masih kosong |
| `Could not read NAMA: …` | Formatnya tidak dikenali Qt, atau berkasnya rusak |
| `NAMA has an unusable size (…)` | Lebar/tinggi nol, atau di atas batas 16384 piksel |

Animasi hanya berjalan untuk GIF dan WebP animasi. Format lain tampil sebagai gambar
diam — itu disengaja, bukan animasi yang gagal.

---

## Hotkey tidak berfungsi

**1. Sudah dipakai aplikasi lain.** Alasannya tampil persis di bawah kolom hotkey di tab
Hotkeys. Pilih kombinasi lain.

**2. F12.** Windows memesannya untuk debugger; `RegisterHotKey` menolaknya. Aplikasi akan
mengatakannya.

**3. Aplikasi lain berjalan sebagai administrator.** Windows tidak mengirim input dari
proses ber-privilese lebih tinggi ke proses biasa. Jalankan overlay sebagai administrator
juga, atau ubah kombinasinya.

---

## Overlay tertutup game

**Exclusive fullscreen melewati DWM sepenuhnya.** Tidak ada strategi `HWND_TOPMOST` yang
bisa menggambar di atasnya — ini batasan Windows, bukan bug.

Pilihan:

- Setel game ke **Borderless Windowed** (atau Windowed Fullscreen).
- Atau: jangan andalkan overlay desktop sama sekali — masukkan grafiknya ke OBS lewat
  Spout2 dan tampilkan di siaran. Overlay desktop lebih tepat dianggap pratinjau lokal.

Kalau aplikasi lain merebut posisi topmost sesekali, naikkan frekuensi
**Re-assert every** di tab Behaviour (500–1000 ms sudah cukup).

---

## Overlay masih di taskbar / Alt-Tab

Aktifkan **Hide from taskbar and Alt-Tab** (tab Behaviour). Kalau tetap muncul, ada kode
yang memasang kembali `WS_EX_APPWINDOW`; log dengan `--log-level DEBUG` akan menunjukkan
perubahan ex-style.

---

## FPS rendah atau patah-patah

Periksa HUD (tab Behaviour → Show the statistics panel):

| Yang terlihat | Artinya |
|---|---|
| FPS rendah, drop 0% | Sumbernya memang lambat — cek FPS di OBS, atau jaringan untuk NDI |
| FPS oke, drop tinggi | Thread GUI tidak sempat melukis; kurangi Target rate atau sederhanakan parsel |
| Jitter tinggi | Beban tidak rata; biasanya OBS atau GPU sedang sibuk |
| Age terus naik | Feed berhenti total; sender kemungkinan hilang |

Ratusan parsel berbentuk elips/poligon membuat `QRegion` punya ribuan rectangle, dan
Windows menelusurinya pada setiap hit test. Tata letak persegi jauh lebih murah — kode
memakai jalur cepat khusus untuk itu.

Khusus `Screen capture`: **Target rate** sekaligus jadi laju grab desktop, dan itu jauh
lebih mahal daripada menerima frame Spout. 30 fps biasanya sudah cukup untuk overlay;
laju grab dibatasi 120 fps apa pun isi profil.

---

## Overlay menutupi semuanya dan mouse tidak bisa dipakai

Tekan **`Ctrl+Alt+Shift+F9`** (panic). Ini mengembalikan click-through, menampilkan
overlay, keluar dari mode editor, dan membuka panel kontrol.

Kalau hotkey itu sendiri tidak terdaftar, klik kanan ikon tray → **Panic — restore input**.

Pengaman bawaan seharusnya mencegah kondisi ini terjadi sama sekali; kalau Anda
mematikannya, hotkey panic adalah jaring pengaman terakhir.

---

## Overlay terekam balik oleh OBS (efek cermin tak terhingga)

Anda meng-capture layar yang sama dengan tempat overlay berada. Aktifkan
**Hide the overlay from screen capture** di tab Behaviour.

Butuh Windows 10 versi 2004 (build 19041) atau lebih baru. Pada build lebih lama,
permintaan diabaikan dan dicatat di log — Windows akan menggambar overlay sebagai kotak
hitam pekat di rekaman, yang lebih buruk daripada tidak melakukan apa pun.

Kalau sumbernya adalah `Screen capture` aplikasi ini sendiri, lihat
[terowongan tak hingga](#tangkapan-layar-jadi-terowongan-tak-hingga) di atas — di sana
pengamannya menyala otomatis.

---

## Profil hilang atau ter-reset

Cari berkas `.corrupt` di `%APPDATA%\obs-overlay\profiles\`. Berkas yang tidak bisa dibaca
dikarantina dengan akhiran itu dan diganti profil default, supaya aplikasi tetap bisa
start. Berkas lamanya masih ada dan bisa diperiksa manual.

Log akan mencatat:

```
WARNING Quarantined unreadable file Default.json -> Default.json.corrupt
```

---

## Aplikasi tidak mau start sama sekali

Jalankan dari baris perintah untuk melihat galat:

```powershell
obs-overlay --log-level DEBUG
```

Untuk build .exe, `ObsOverlay.exe` dibangun tanpa console. Jalankan dengan argumen yang
tidak membuka GUI supaya galat impor terlihat:

```powershell
.\ObsOverlay.exe --version
```

Kalau tetap diam saja, periksa log — pengecualian yang tidak tertangkap tetap dicatat
ke sana lewat excepthook.

---

## Mendapatkan bantuan

Saat melaporkan masalah, sertakan:

1. Versi Windows (`winver`)
2. Sumber yang dipakai, plus versi OBS/plugin Spout2 atau versi NDI Runtime kalau relevan
3. Keluaran `obs-overlay --version` dan `obs-overlay --list-senders` (tambahkan
   `--source ndi` atau `--source screen` sesuai sumber yang bermasalah)
4. Potongan `obs-overlay.log` yang relevan (jalankan dengan `--log-level DEBUG` dulu)
5. Profil Anda (tab Profiles → **Export**) — berkas JSON biasa, aman dibagikan
