# Yang bisa dikerjakan berikutnya

Bukan janji, melainkan daftar pilihan beserta alasannya. Urut dari yang paling
berharga. Setiap butir menyebut perkiraan usaha dan apa yang perlu disentuh,
supaya bisa langsung diserahkan ke agent AI.

Status sekarang: v1.1.0, 381 tes lulus, CI hijau, installer terbentuk. Yang
belum pernah diuji di perangkat sungguhan ada di
**[WINDOWS_CHECKLIST.md](WINDOWS_CHECKLIST.md)**.

---

## Prioritas 1 — sebelum menambah apa pun

### Jalankan checklist Windows
**Usaha:** satu sesi. **Nilai:** paling tinggi, sejauh ini.

Seluruh jalur Win32, Spout, dan NDI ditulis dari dokumentasi resmi dan belum
pernah dieksekusi. Menambah fitur di atas fondasi yang belum terbukti hanya
menumpuk risiko. Bug entry point yang membuat `.exe` mati total bertahan
melewati satu rilis persis karena tidak ada yang pernah menjalankannya.

### Tandatangani .exe (Authenticode)
**Usaha:** kecil, tapi berbiaya. **Nilai:** tinggi untuk pengguna lain.

SmartScreen memperingatkan setiap unduhan tanpa tanda tangan, dan heuristik
Defender memang mengincar bootloader PyInstaller. Sertifikat OV sekitar
US$200–400/tahun; EV lebih mahal tapi langsung punya reputasi SmartScreen.

Kalau hanya dipakai sendiri, lewati saja — mitigasi lain (one-dir, tanpa UPX,
VS_VERSION_INFO lengkap) sudah diterapkan. Rinciannya di
[BUILD.md](BUILD.md#antivirus-melaporkan-false-positive).

### Tutup atau buktikan bug shutdown
**Usaha:** kecil kalau ternyata tidak terjadi di Windows.

Lihat butir 12 di checklist. Kalau 10 kali tutup di Windows selalu bersih,
catat itu di `CHANGELOG.md` dan tutup isunya sebagai artefak QPA offscreen.

---

## Prioritas 2 — fitur yang paling mengubah cara pakai

### Setiap parsel menampilkan bagian sumber yang berbeda
**Usaha:** sedang. **Nilai:** ini fitur yang paling mengubah aplikasi.

Sekarang semua parsel adalah *lubang* ke satu gambar yang sama. Kalau setiap
parsel bisa punya *source rect* sendiri, satu scene OBS bisa dipecah ke
beberapa kotak di posisi bebas di layar — misalnya timer di pojok kiri, chat di
kanan bawah, alert di tengah, semuanya dari satu feed.

Yang disentuh:
- `config/models.py` — `Parcel.source_rect: RectSpec | None`, migrasi v3 → v4
- `ui/overlay_window.py` — `paintEvent` menggambar per parsel
  (`drawImage(target, image, source)`) alih-alih sekali untuk seluruh kanvas
- `ui/editor.py` — cara memilih area sumber; paling sederhana: dialog dengan
  pratinjau, bukan editor kedua di layar
- `core/geometry.py` — pemetaan koordinat, murni fungsi, mudah diuji

Hati-hati: jalur cepat "ukuran sumber = ukuran kanvas, tanpa transformasi" akan
hilang untuk parsel yang punya source rect. Ukur ulang FPS-nya.

### Tangkap satu jendela, bukan satu monitor
**Usaha:** sedang. **Nilai:** tinggi.

`ScreenSource` menangkap monitor atau region. Menangkap **jendela tertentu**
lebih berguna: jendela chat, timer, atau skor yang tetap ikut meski jendelanya
dipindah.

Dua jalur:
- `QScreen.grabWindow(hwnd)` — sederhana, tetapi gagal pada jendela ber-GPU dan
  ikut mengambil apa pun yang menimpanya.
- Windows Graphics Capture API (`Windows.Graphics.Capture`) — benar, tidak
  peduli jendelanya tertimpa, tetapi butuh binding WinRT dan Windows 10 1903+.

Mulai dari yang pertama, dokumentasikan batasannya, naikkan kalau perlu.

### Ganti profil otomatis mengikuti scene OBS
**Usaha:** sedang. **Nilai:** tinggi kalau dipakai untuk siaran.

obs-websocket v5 sudah ada di OBS 28+. Berlangganan `CurrentProgramSceneChanged`
lalu memuat profil bernama sama membuat tata letak parsel berubah sendiri saat
ganti scene.

Menambah satu dependensi (`websockets` atau `simpleobsws`). Buat **opsional**
seperti NDI: impor di dalam fungsi, extra tersendiri di `pyproject.toml`.

---

## Prioritas 3 — sumber tambahan

Resepnya sudah baku, ada di `CLAUDE.md` (bagian *Adding a video source*).
Masing-masing sekitar setengah hari termasuk tes dan dokumentasi.

| Sumber | Cara | Catatan |
|---|---|---|
| **Webcam** | `QMediaDevices` + `QMediaCaptureSession` | Tidak ada alpha; berguna untuk PiP di dalam parsel |
| **Berkas video** | `QMediaPlayer` + `QVideoSink` | Looping, alpha hanya pada format yang mendukung |
| **Halaman web** | `QtWebEngine` | **Jangan.** Menambah ~250 MB ke bundle dan satu kelas masalah baru. Pakai Browser Source di OBS lalu kirim lewat Spout. |
| **Syphon** | — | macOS saja, dan aplikasi ini menargetkan Windows |

---

## Prioritas 4 — kualitas hidup

| Ide | Usaha | Catatan |
|---|---|---|
| **Antarmuka bahasa Indonesia** | Sedang | Dokumentasi sudah Indonesia, UI masih Inggris. Butuh `QTranslator` + berkas `.ts`. Konsisten kalau installer-nya ikut diterjemahkan (butuh `.isl` Indonesia tidak resmi). |
| **Cek pembaruan otomatis** | Kecil | Baca GitHub Releases API, bandingkan dengan `APP_VERSION`, tampilkan notifikasi tray. Jangan mengunduh sendiri — cukup buka halaman rilis. |
| **Opacity per parsel** | Kecil | Sekarang opacity bersifat global. Satu field di `Parcel`, satu migrasi, satu `setOpacity` di `paintEvent`. |
| **Impor/ekspor tata letak saja** | Kecil | Sekarang profil dibagikan utuh, termasuk nama sender dan monitor — yang tidak relevan di mesin lain. |
| **Pratinjau parsel di panel** | Sedang | Peta kecil di tab Parcels supaya tata letak terlihat tanpa masuk mode editor. |
| **Beberapa overlay sekaligus** | Besar | Satu overlay per monitor dengan sumber berbeda. Perubahan arsitektur: `OverlayApplication` sekarang mengasumsikan satu jendela dan satu producer. Jangan dikerjakan sebelum ada yang benar-benar membutuhkannya. |

---

## Yang sebaiknya **tidak** dikerjakan

| Ide | Kenapa tidak |
|---|---|
| Pindah ke `QOpenGLWidget` demi performa | Akan menghilangkan hit-testing per-piksel — inti aplikasi ini. Menggambar 1080p memakan 0,6 ms; performa bukan masalahnya. Lihat Keputusan 1 di [ARCHITECTURE.md](ARCHITECTURE.md). |
| `--onefile` supaya unduhannya satu berkas | Mengekstrak ~150 MB ke `%TEMP%` setiap kali dijalankan, dan penyebab utama false positive antivirus. Installer sudah menyelesaikan masalah "satu berkas". |
| Menambah OpenCV atau Pillow | `QPainter` dan numpy sudah cukup. `opencv-python` menautkan Qt-nya sendiri dan bisa menghasilkan galat "Could not load the Qt platform plugin". |
| UPX untuk mengecilkan bundle | DLL inti Qt yang dikompres UPX punya sejarah crash diam-diam, dan pengepakan UPX adalah salah satu heuristik antivirus terkuat. |
| Mengganti impor absolut di `__main__.py` | Itu yang membuat `.exe` bisa hidup. Lihat daftar invarian di `CLAUDE.md`. |

---

## Cara menyerahkan ini ke agent AI

Kalimat yang cukup:

> Baca `CLAUDE.md` dan `docs/ROADMAP.md`. Kerjakan <butir>. Jalankan seluruh
> quality gate sebelum commit.

Agent akan menemukan sendiri invarian, resep, dan perintahnya. Untuk pekerjaan
verifikasi, tunjuk ke `docs/WINDOWS_CHECKLIST.md` dan minta hasilnya dicatat
di situ.
