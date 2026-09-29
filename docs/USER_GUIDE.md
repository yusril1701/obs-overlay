# Panduan pengguna

Penjelasan setiap setelan di panel kontrol. Panel dibuka dengan `Ctrl+Alt+P`, lewat ikon
di system tray, atau klik kanan overlay saat mode editor aktif.

---

## Tab Source — sumber video

Pilihan **Source** di paling atas menentukan dari mana gambar datang. Setelan di
bawahnya berganti mengikuti pilihan itu — tapi nilai untuk sumber lain **tidak
hilang**, jadi berpindah bolak-balik aman.

| Pilihan | Untuk apa | Butuh apa |
|---|---|---|
| `OBS via Spout2` | Scene OBS lengkap, alpha penuh, satu mesin | SpoutGL + filter Spout di OBS |
| `NDI (network)` | Sumber dari mesin lain di jaringan | `ndi-python` + NDI Runtime |
| `Screen capture` | Satu monitor atau sepotong area layar | tidak ada |
| `Image file` | PNG/GIF/WebP — logo, bingkai, watermark | tidak ada |
| `Built-in test pattern` | Menata parsel tanpa sumber apa pun | tidak ada |

Kalau sumber yang dipilih tidak bisa dipakai di mesin ini, alasannya langsung
muncul sebagai teks abu-abu di bawah pilihan — bukan baru ketahuan saat overlay
diam.

### Setelan yang berlaku untuk semua sumber

| Setelan | Penjelasan |
|---|---|
| **Target rate** | Berapa kali per detik penerima memeriksa frame baru. Samakan dengan FPS sumber; lebih tinggi hanya membakar CPU. Untuk `Screen capture` ini sekaligus jadi laju grab, dibatasi 120 fps. |
| **Reconnect automatically** | Coba sambung ulang terus-menerus saat sumber hilang, dengan jeda yang membesar (1 → 8 detik). |
| **Fall back to the test pattern…** | Kalau dependensi sumber tidak terpasang, pakai pola uji. **Mati secara bawaan** — saat siaran langsung, overlay kosong lebih aman daripada pola uji muncul tiba-tiba. |

Bagian **Connection** di bawahnya menunjukkan status, resolusi, FPS aktual, serta jumlah
frame diterima dan dibuang, ditambah tombol **Reconnect now**.

### `OBS via Spout2`

| Setelan | Penjelasan |
|---|---|
| **Sender name** | Nama Spout sender. Klik **Refresh** untuk memindai. Kosongkan untuk selalu mengikuti sender yang sedang aktif. |
| **Use any available sender…** | Kalau nama yang ditulis tidak sedang menyiarkan tapi ada sender lain, ikuti yang itu. Mencegah overlay diam menunggu nama yang salah ketik. |
| **Flip vertically during receive** | Balik baris piksel saat menerima. Pakai ini kalau feed terbalik; lebih murah daripada memutar di tab Display karena dikerjakan Spout. |
| **Sender uses premultiplied alpha** | **Biarkan aktif untuk OBS.** Lihat [catatan alpha](#soal-alpha-premultiplied) di bawah. |

### `NDI (network)`

| Setelan | Penjelasan |
|---|---|
| **NDI source** | Nama sumber, biasanya `MESIN (Nama Output)`. **Scan** memindai jaringan; pemindaian butuh beberapa detik karena NDI memakai mDNS. |
| **Use any available source…** | Ikuti sumber pertama yang ditemukan kalau nama yang ditulis tidak ada. |
| **Source uses premultiplied alpha** | **Mati secara bawaan** — spesifikasi NDI menyatakan datanya *tidak* premultiplied. Nyalakan hanya kalau tepi lembut terlihat pucat. |
| **Low bandwidth (proxy resolution)** | Minta aliran resolusi rendah. Jauh lebih hemat jaringan, cocok saat menata parsel lewat koneksi lambat. |

NDI butuh dua hal terpisah: paket Python `ndi-python` (`pip install ndi-python`)
**dan** NDI Runtime dari NDI.tv, yang dipasang sendiri karena lisensinya.

### `Screen capture`

| Setelan | Penjelasan |
|---|---|
| **Monitor** | Monitor yang ditangkap. Daftarnya ikut monitor yang benar-benar tersambung. |
| **Capture only part of the monitor** | Tangkap sepotong saja, bukan seluruh monitor. |
| **Region X/Y/W/H** | Kotak yang ditangkap, **relatif terhadap sudut kiri-atas monitor yang dipilih**, bukan terhadap virtual desktop. |
| **Hide the overlay from its own capture** | Lihat [terowongan tak hingga](#terowongan-tak-hingga) di bawah. Biarkan aktif. |

### `Image file`

| Setelan | Penjelasan |
|---|---|
| **Image file** | Berkas PNG, GIF, WebP, JPEG, atau BMP. Transparansi PNG/GIF/WebP dipertahankan apa adanya. |
| **Play animation** | Untuk GIF dan WebP animasi. Kalau dimatikan, hanya frame pertama yang tampil. |

Gambar diam dikirim sekali lalu berhenti — tidak ada CPU yang terpakai untuk
menggambar ulang frame yang sama.

### Terowongan tak hingga

`Screen capture` yang menangkap monitor tempat overlay berada akan memotret
overlay itu sendiri, lalu memotret hasil potretnya, dan seterusnya.

Aplikasi mendeteksi tumpang tindih antara area tangkap dan jendela overlay, lalu
menyalakan **capture exclusion** (`WDA_EXCLUDEFROMCAPTURE`) secara otomatis
selama opsi **Hide the overlay from its own capture** aktif. Butuh Windows 10
versi 2004 ke atas; di bawah itu pindahkan overlay ke monitor lain atau tangkap
sebuah region yang tidak bersinggungan dengan overlay.

---

## Tab Display — penempatan dan framing

### Placement

| Setelan | Penjelasan |
|---|---|
| **Covers** | `Primary monitor`, `Specific monitor`, `All monitors` (virtual desktop), atau `Custom rectangle`. |
| **Monitor** | Aktif kalau mode `Specific monitor`. Kalau monitornya dicabut, aplikasi otomatis kembali ke monitor utama. |
| **Rectangle** | Aktif kalau mode `Custom rectangle`. Koordinat dalam piksel logis desktop. |

### Framing

| Setelan | Penjelasan |
|---|---|
| **Fit** | `Contain` (bawaan, muat penuh tanpa distorsi), `None` (1:1 seperti blueprint), `Cover` (penuhi, boleh terpotong), `Stretch` (penuhi, boleh distorsi). |
| **Anchor** | Posisi video di dalam kanvas kalau ada ruang sisa. |
| **Zoom** | Pengali tambahan di atas mode Fit. |
| **Offset** | Geser video beberapa piksel dari posisi anchor. |
| **Opacity** | Transparansi global seluruh overlay. |
| **Mirror** | Cermin horizontal / vertikal. |
| **Scaling** | `Smooth` (bilinear) atau `Fast` (nearest). Tidak berpengaruh sama sekali kalau ukuran sumber sama dengan kanvas — tidak ada transformasi yang terjadi. |

> **Kenapa bawaannya `Contain`, bukan `None`?**
> Blueprint mengasumsikan kanvas OBS berukuran sama dengan layar. Kalau memang begitu,
> `Contain` dan `None` menghasilkan hasil identik. Kalau berbeda, `Contain` tetap masuk
> akal sementara `None` akan memotong atau menyisakan ruang kosong. Pilih `None` kalau
> Anda memang ingin piksel 1:1 apa pun yang terjadi.

---

## Tab Parcels — kotak-kotak

Tabel ini dan editor di layar adalah dua tampilan untuk data yang sama; mengubah salah
satu langsung terlihat di yang lain.

| Kolom | Arti |
|---|---|
| **Name** | Label bebas, muncul di editor. |
| **X, Y, W, H** | Posisi dan ukuran dalam piksel, relatif terhadap sudut kiri-atas overlay. |
| **Shape** | `Rectangle`, `Rounded`, `Ellipse`, atau `Polygon`. |
| **Radius** | Radius sudut; hanya aktif untuk `Rounded`. Otomatis dibatasi setengah sisi terpendek. |
| **Mode** | `Add` menambah area; `Cut` **mengurangi** parsel yang ada di atasnya dalam daftar. |
| **On** | Nonaktifkan sementara tanpa menghapus. |
| **Lock** | Kunci dari perubahan lewat editor. |

**Tombol**: Add, Duplicate, Delete, Grid layout (buat kisi N×M sekaligus), Select all,
serta baris align/distribute.

Baris status di bawah tabel menunjukkan berapa persen layar yang tertutup, dan akan
memperingatkan kalau tata letaknya berbahaya.

### Membuat lubang

Urutan dalam daftar = urutan tumpukan. Untuk melubangi sebuah kotak:

1. Buat parsel besar (`Add`).
2. Buat parsel kecil di atasnya dalam daftar, ubah **Mode** jadi `Cut`.

---

## Tab Behaviour — perilaku jendela

| Setelan | Penjelasan |
|---|---|
| **Click through the overlay** | Mouse tembus ke aplikasi di belakang. Otomatis ditangguhkan selama mode editor terbuka. |
| **Always on top** | Jaga overlay di atas jendela lain. |
| **Re-assert every** | Seberapa sering posisi topmost ditegakkan ulang. Beberapa aplikasi fullscreen merebutnya. `0` mematikan timer. |
| **Hide from taskbar and Alt-Tab** | Jadikan tool window. |
| **Never take keyboard focus** | Pasang `WS_EX_NOACTIVATE`; overlay tidak akan mencuri fokus dari game. |
| **Hide the overlay from screen capture** | Overlay tidak terekam OBS/perekam layar. Butuh Windows 10 versi 2004 ke atas; di bawah itu permintaan diabaikan (bukan diterapkan setengah-setengah). |
| **Cut the window into parcels** | Matikan untuk menampilkan seluruh feed sebagai satu kotak. |
| **Warn before a layout that could trap the mouse** | Pengaman; lihat bawah. |
| **Keep running in the system tray when closed** | Menutup panel tidak mengakhiri aplikasi. |
| **Open this panel at startup** | |

### Pengaman

Kalau parsel menutupi ≥92% layar **dan** click-through mati **dan** opacity ≥50%, Anda
tidak akan bisa mengklik apa pun di desktop — termasuk ikon tray untuk memperbaikinya.

Aplikasi mendeteksi kondisi ini, menyalakan kembali click-through, dan memberi tahu lewat
notifikasi tray. Kalau memang itu yang Anda mau, matikan pengamannya.

Hotkey **panic** (`Ctrl+Alt+Shift+F9`) selalu tersedia: mengembalikan click-through,
menampilkan overlay, keluar dari mode editor, dan membuka panel.

---

## Tab Editor — perilaku editor

| Setelan | Penjelasan |
|---|---|
| **Grid size** | Jarak grid dalam piksel. Juga jadi besar langkah `Shift`+panah. |
| **Snapping** | Ke grid, ke parsel lain, dan ke tepi/tengah layar. Bisa dipilih sendiri-sendiri. |
| **Snap distance** | Jarak maksimum (piksel) sebelum snap aktif. `0` mematikan snapping. |
| **Guides** | Tampilkan grid, garis bantu perataan, dan label nama/ukuran. |
| **Editor dimming** | Seberapa gelap latar saat mode editor, supaya batas jendela terlihat jelas. |

Snapping ke objek selalu menang atas snapping ke grid kalau keduanya dalam jangkauan —
merapikan terhadap kotak tetangga hampir selalu yang dimaksud pengguna.

---

## Tab Hotkeys

Klik sebuah kolom lalu tekan kombinasinya. `Backspace` atau `Delete` untuk mengosongkan.

Kombinasi tanpa modifier ditolak — hotkey global tanpa Ctrl/Alt/Shift/Win akan menelan
tombol itu di seluruh sistem.

Kalau sebuah kombinasi sudah dipakai aplikasi lain, alasannya muncul tepat di bawah
kolomnya dan Anda bisa memilih yang lain. **F12 tidak bisa dipakai** — Windows
memesannya untuk debugger.

---

## Tab Profiles

Satu profil = satu setup lengkap (sumber, penempatan, parsel, perilaku, hotkey).

- **New / Duplicate / Rename / Delete**
- **Import / Export** — berkas JSON biasa, aman untuk dibagikan atau dimasukkan ke git.
- **Open folder** — buka `%APPDATA%\obs-overlay\`

Impor tidak pernah menimpa: kalau namanya bentrok, profil masuk sebagai `Nama (2)`.

---

## Tab About

Versi aplikasi, Python, Qt, status SpoutGL **dan NDI**, lokasi folder data dan log, serta
ringkasan langkah setup OBS.

---

## HUD statistik

Dinyalakan di tab Behaviour (**Show the statistics panel on the overlay**).

| Baris | Arti |
|---|---|
| **Status** | Connected / Connecting / Error |
| **Sender** | Apa yang sedang terhubung — nama Spout sender, nama sumber NDI, monitor yang ditangkap, atau nama berkas gambar |
| **Size** | Resolusi sumber |
| **FPS** | Aktual / target. Hijau ≥90% target, kuning ≥60%, merah di bawah itu. |
| **Frames** | Diterima (dibuang, persentase) |
| **Age** | Usia frame terakhir — kalau terus naik, feed berhenti |
| **Jitter** | Ketidakteraturan jarak antar frame; mendekati nol berarti mulus |

---

## Soal alpha premultiplied

OBS menyusun scene dengan alpha premultiplied, artinya kanal warna sudah dikalikan alpha
sebelum dikirim. NDI sebaliknya: spesifikasinya menyatakan datanya *tidak* premultiplied.
Karena itu bawaannya berbeda per sumber:

| Sumber | Bawaan | Alasan |
|---|---|---|
| Spout | **aktif** | Filter Spout OBS mengirim premultiplied |
| NDI | **nonaktif** | Spesifikasi NDI: "not pre-multiplied" |
| Screen capture | — | Tangkapan layar selalu opaque, tidak ada alpha |
| Image file | nonaktif | PNG/GIF/WebP memakai straight alpha |

Kalau salah setel, gejalanya terlihat jelas di tepi yang antialias (teks, lingkaran):

| | Sumber premultiplied (OBS) | Sumber straight alpha (NDI, PNG) |
|---|---|---|
| Aktif | Benar | Tepi pucat / terlalu terang |
| Nonaktif | **Tepi bergaris gelap** | Benar |

---

## Di mana semuanya disimpan

```
%APPDATA%\obs-overlay\
├── settings.json          profil aktif, level log
├── profiles\
│   └── Default.json
└── logs\
    └── obs-overlay.log    berputar, maks 2 MB × 4 berkas
```

Mode portable: buat berkas kosong bernama `portable.txt` di sebelah `ObsOverlay.exe`.
Semua data akan disimpan di subfolder `data\` di situ — cocok untuk flash disk.
