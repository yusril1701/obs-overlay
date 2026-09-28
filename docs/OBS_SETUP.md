# Menyiapkan OBS Studio

Panduan lengkap untuk mengeluarkan feed **transparan** dari OBS lewat Spout2.

Urutannya penting. Kalau overlay tampil hitam atau buram, hampir selalu penyebabnya ada
di langkah 2 atau langkah 6 di bawah.

---

## 1. Pasang plugin Spout2

Plugin resmi: **[Off-World-Live/obs-spout2-plugin](https://github.com/Off-World-Live/obs-spout2-plugin)**
(GPL v2, Windows 64-bit saja). Versi 1.12.0 dibangun untuk OBS Studio 32.1.2 dan bekerja
dengan OBS 30/31/32.

Ada dua cara pasang:

**Installer (paling mudah)**
Unduh `OBS_Spout2_Plugin_Install_v<versi>.exe` dari halaman Releases, jalankan, selesai.

**Manual (zip)**
Unduh `win-spout-<versi>-windows-x64.zip`, ekstrak foldernya ke:

```
C:\ProgramData\obs-studio\plugins\
```

Hasil akhirnya harus seperti ini:

```
C:\ProgramData\obs-studio\plugins\win-spout\bin\64bit\win-spout.dll
C:\ProgramData\obs-studio\plugins\win-spout\data\locale\en-US.ini
```

> Untuk OBS portable, pakai zip yang berakhiran `-portable` dan ekstrak ke folder root
> OBS. Struktur folder localenya berbeda (`data/obs-plugins/win-spout/locale/`).

**Restart OBS** setelah memasang.

Kalau plugin terpasang benar, Anda akan melihat:
- source baru bernama **Spout2 Capture**,
- filter baru bernama **Spout Filter**,
- menu **Tools → Spout Output Settings**.

---

## 2. Setel Color Format ke BGRA

**Ini langkah yang paling sering terlewat.**

```
Settings → Advanced → Video → Color Format → BGRA (8-bit)
```

Format bawaan OBS adalah NV12, yang **tidak punya alpha channel sama sekali**. Selama
masih NV12, apa pun yang Anda lakukan, feed yang keluar akan opaque.

Klik **Apply**.

---

## 3. Tambahkan "Spout Filter" ke scene

Klik kanan **scene** (atau satu source tertentu) di panel Sources →
`Filters` → tombol `+` di bawah **Effect Filters** → **Spout Filter**.

### Kenapa filter, bukan Tools → Spout Output?

| | Spout Filter | Tools → Spout Output |
|---|---|---|
| Alpha | **Dipertahankan** | Hilang |
| Sumber | source/scene tertentu | main mix OBS |
| Mengunci output OBS | Tidak | **Ya** |

Filter membuat texture `GS_BGRA_UNORM` sendiri, membersihkannya ke RGBA(0,0,0,0), lalu
merender source ke situ — alpha ikut terbawa. Sementara `Tools → Spout Output` mengambil
main mix, yang formatnya NV12, jadi alphanya sudah hilang sebelum sampai ke Spout. Jalur
itu juga memanggil `obs_output_begin_data_capture()` sehingga output OBS terkunci.

---

## 4. Beri nama sender — dan tekan tombolnya

Di properti filter ada kolom teks **Spout** dan tombol **Change Spout Filter Name**.

1. Ketik nama yang Anda mau, misalnya `OBS_Sender`.
2. **Klik tombol "Change Spout Filter Name".**

> **Wajib diklik.** Properti filter ini memakai `OBS_PROPERTIES_DEFER_UPDATE`, artinya
> mengetik saja tidak mengubah apa pun — nama baru baru dipakai setelah tombol ditekan.
> Kalau dilewati, sender Anda akan tetap bernama `Spout_OBS_Filter` (nama bawaan).

Nama sender harus **unik**. Dua filter dengan nama sama akan berebut shared memory yang
sama.

---

## 5. Aktifkan "Continuous filter broadcast"

```
Tools → Spout Output Settings → centang "Continuous filter broadcast"
```

Secara bawaan, Spout Filter hanya mengirim frame **selama source induknya sedang
dirender OBS**. Begitu Anda pindah ke scene lain, sender langsung hilang dari daftar dan
overlay jadi kosong.

Dengan opsi ini dicentang, filter memanggil `obs_source_inc_showing()` pada induknya
sehingga rendering tetap jalan di belakang layar.

> Ini setelan **global** untuk semua Spout Filter, walaupun letaknya di dialog Tools.

---

## 6. Pastikan backgroundnya benar-benar transparan

Alpha hanya ada kalau memang tidak ada yang menggambar di belakangnya. Periksa:

- **Tidak ada Color Source** atau gambar latar di bawah stack scene.
- **Browser Source**: transparansi tidak otomatis. Custom CSS bawaan OBS
  (`body { background-color: rgba(0, 0, 0, 0); }`) hanya mengosongkan background `body`.
  Halaman yang menyetel background sendiri pada `html`, `body`, atau div pembungkus tetap
  akan opaque. Tambahkan `!important`, atau perbaiki halamannya.
- **Urutan filter penting.** Spout Filter memanggil `obs_source_video_render(parent)` lalu
  `obs_source_skip_video_filter()`, jadi filter yang ada **di bawahnya** tidak ikut
  terkirim. Taruh Color Correction / Chroma Key **di atas** Spout Filter.

### Cara membaca preview OBS

- **Kotak-kotak catur** = transparan. Bagus.
- **Hitam pekat** = ada sesuatu yang benar-benar menggambar warna hitam. Itu bukan
  masalah plugin.

> Jangan memakai aplikasi demo `SpoutReceiver` bawaan SDK untuk memeriksa alpha — demo itu
> menggambar di atas latar hitam, jadi area transparan akan terlihat hitam walaupun
> alphanya baik-baik saja. Pakai overlay ini, atau OBS kedua dengan source
> **Spout2 Capture** dan Composite mode **Premultiplied Alpha**.

---

## 7. Hubungkan overlay

Di aplikasi ini:

1. Buka panel kontrol (`Ctrl+Alt+P` atau klik ikon tray).
2. Tab **Source** → klik **Refresh**.
3. Pilih nama sender Anda dari daftar.

Status di bawah akan berubah jadi **Connected** beserta resolusinya.

---

## Catatan penting soal alpha premultiplied

OBS menyusun scene dengan operator "over" premultiplied
(`gs_blend_function_separate(ONE, INVSRCALPHA, ONE, INVSRCALPHA)`). Artinya nilai
R, G, dan B yang keluar dari Spout Filter **sudah dikalikan** dengan alpha.

Aplikasi ini sudah menyetel **"Sender uses premultiplied alpha" = aktif** secara bawaan,
yang benar untuk OBS. Anda hanya perlu mematikannya kalau memakai sender lain yang
mengirim alpha lurus (*straight alpha*).

Gejala kalau setelannya salah:

| Setelan | Sumber premultiplied (OBS) | Sumber straight |
|---|---|---|
| Aktif (bawaan) | Benar | Tepi terlihat pucat/terlalu terang |
| Nonaktif | Tepi bergaris gelap | Benar |

Paling mudah dilihat pada teks atau bentuk dengan tepi halus (antialias).

---

## Resolusi dan frame rate

- **Resolusi sender = ukuran dasar source yang difilter**, bukan kanvas OBS. Filter pada
  Browser Source 300×200 menghasilkan sender 300×200. Kalau filternya dipasang di
  **scene**, ukurannya sama dengan `Settings → Video → Base (Canvas) Resolution`.
  Overlay ini menangani perubahan ukuran saat berjalan secara otomatis.
- **Frame rate = FPS render OBS** (`Settings → Video → Common FPS Values`).
- Ada **satu frame latensi** bawaan: plugin sengaja memakai double-buffer (mengirim frame
  sebelumnya lalu menukar buffer) untuk menghindari GPU flush dan memperbaiki masalah
  G-Sync. Pada 60 FPS itu sekitar 16 ms. Ini normal.

---

## Spout hanya bekerja dalam satu GPU

Dokumentasi plugin menyebutkannya langsung: *"This plugin only works for video sharing on
a single GPU."*

Di laptop hybrid (Intel iGPU + NVIDIA/AMD dGPU), OBS bisa saja jalan di satu GPU sementara
aplikasi ini di GPU lain. Hasilnya: sender terlihat di daftar tapi tidak pernah ada frame,
atau layar hitam.

**Solusi:**

```
Windows Settings → System → Display → Graphics
```

Tambahkan **`obs64.exe`** dan **`ObsOverlay.exe`** (atau `python.exe` kalau menjalankan
dari source), lalu setel keduanya ke **High performance**. Restart kedua aplikasi.

---

## Daftar periksa cepat

- [ ] Plugin Spout2 terpasang, OBS sudah di-restart
- [ ] `Settings → Advanced → Color Format` = **BGRA (8-bit)**
- [ ] **Spout Filter** ditambahkan ke scene (bukan Tools → Spout Output)
- [ ] Nama sender diisi **dan** tombol *Change Spout Filter Name* ditekan
- [ ] **Continuous filter broadcast** dicentang
- [ ] Tidak ada Color Source / background opaque di scene
- [ ] Preview OBS menampilkan kotak-kotak catur, bukan hitam
- [ ] OBS dan overlay memakai GPU yang sama
