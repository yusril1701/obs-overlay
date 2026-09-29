# Arsitektur

Dokumen ini menjelaskan bagaimana aplikasi disusun dan — yang lebih penting — **kenapa**
beberapa keputusan diambil seperti itu. Beberapa di antaranya berbeda dari blueprint asli,
dan alasannya dicatat di sini supaya tidak "diperbaiki" kembali menjadi salah.

---

## Peta modul

```
obs_overlay/
├── constants.py        Nilai tetap. Tanpa dependensi selain stdlib.
├── paths.py            Lokasi %APPDATA%, mode portable, folder bundle.
├── logging_setup.py    Log berputar + excepthook (penting untuk build windowed).
├── cli.py              Argparse; tidak menyentuh Qt sebelum perlu.
├── app.py              Perakitan: menyambungkan semua bagian. Tidak punya logika sendiri.
│
├── config/
│   ├── models.py       Dataclass profil. Setiap from_dict() total dan tahan input rusak.
│   ├── migrations.py   Upgrade skema v1 → v2 → v3.
│   └── store.py        Tulis atomik, karantina file rusak, kelola profil.
│
├── core/
│   ├── geometry.py     Matematika editor. Bebas Qt, bebas platform, 100% bisa diuji.
│   ├── mask.py         Parsel → QRegion (mask) dan → QPainterPath (clip).
│   ├── frame.py        Frame + buffer pool daur ulang.
│   ├── fps.py          Statistik dan pacer frame.
│   └── producer.py     QThread penerima. Latest-wins.
│
├── sources/
│   ├── base.py         Antarmuka VideoSource.
│   ├── spout_source.py Penerima Spout2 (Windows).
│   ├── ndi_source.py   Penerima NDI lewat ndi-python (lintas platform).
│   ├── screen_source.py Tangkapan monitor/region; grabber hidup di thread GUI.
│   ├── image_source.py Berkas gambar diam atau animasi (QMovie).
│   ├── demo_source.py  Pola uji animasi (semua platform).
│   ├── qt_frames.py    QImage → Frame dari pool, menangani stride.
│   └── registry.py     Pabrik; setiap impor opsional dibuat malas.
│
├── native/             Integrasi Win32, dengan stub no-op di platform lain.
│   ├── base.py         Antarmuka + implementasi Null.
│   ├── win32_window.py Click-through, topmost, tool window, capture exclusion.
│   ├── hotkey_spec.py  Parser string hotkey. Bebas ctypes → bisa diuji di mana saja.
│   └── hotkeys.py      RegisterHotKey + native event filter.
│
└── ui/
    ├── overlay_window.py  Jendela overlay. Satu widget, satu paintEvent.
    ├── editor.py          State machine editor parsel.
    ├── control_panel.py   Jendela setelan bertab.
    ├── parcel_table.py    Tabel parsel yang bisa diedit.
    ├── tray.py            Ikon dan menu tray.
    ├── hud.py             Panel statistik di atas overlay.
    └── theme.py / icons.py / widgets.py
```

**Aturan lapisan:** `core/geometry.py` tidak mengimpor Qt. `config/` tidak mengimpor Qt.
`native/` tidak mengimpor `ui/`. Itulah sebabnya 300+ tes bisa jalan tanpa GPU, tanpa
Windows, dan tanpa OBS.

---

## Alur data satu frame

```
OBS    ──(Spout2, shared GPU memory)──►  SpoutReceiver.receiveImage()
jaringan ──(NDI)────────────────────►  recv_capture_v2()          │
layar  ──(QScreen.grabWindow)───────►  _ScreenGrabber.take()      ├─► satu buffer pool
berkas ──(QImage / QMovie)──────────►  frame_from_qimage()        │
                                            │  mengisi buffer dari pool
                                            ▼
                                        Frame(buffer, w, h, premultiplied)
                                            │  publish latest-wins
                                            ▼  (signal antar-thread)
                                        OverlayWindow.set_frame()
                                            │  QImage sebagai *view*, tanpa copy
                                            ▼
                                        paintEvent → setClipPath(parcels) → drawImage
                                            │
                                            ▼
                                        Qt backing store (ARGB32_Premultiplied)
                                            │
                                            ▼
                                        UpdateLayeredWindowIndirect(ULW_ALPHA)
```

---

## Keputusan 1 — Raster, bukan OpenGL

Blueprint menyebutkan jalur `QLabel`/`QPixmap`. Aplikasi ini memakai `paintEvent` khusus,
tapi tetap pada **backing store raster Qt**, bukan `QOpenGLWidget`. Ini disengaja.

Di Windows, Qt memperlakukan dua jenis surface secara berbeda
(`qwindowswindow.cpp`, `qwindowsbackingstore.cpp`):

| | Raster (dipakai di sini) | OpenGL surface |
|---|---|---|
| Alpha per-piksel | `UpdateLayeredWindowIndirect(..., ULW_ALPHA)` | `SetLayeredWindowAttributes` + trik `DwmEnableBlurBehindWindow` |
| Hit-testing per-piksel | **Ya** — piksel dengan alpha 0 otomatis tembus klik | **Tidak** |
| Butuh `QSurfaceFormat` manual | Tidak (Qt menaikkan alphaBufferSize sendiri) | Ya, sebelum `QApplication` |
| Update parsial | Ya, dengan dirty rect | Selalu penuh |

Jalur raster memberi transparansi yang lebih dapat diandalkan **dan** tembus-klik gratis
di area kosong, tanpa bergantung pada trik DWM yang perilakunya berbeda antar driver.

Biayanya kecil dan terukur: menggambar `QImage` RGBA8888 1920×1080 memakan sekitar
**0,6 ms** — sekitar 3,5% dari anggaran 16,6 ms pada 60 FPS.

> Catatan pengukuran: mengonversi frame ke `ARGB32_Premultiplied` dulu **lebih lambat**
> (≈2,3 ms konversi + 0,45 ms gambar) dibanding menggambar RGBA8888 langsung (≈0,6 ms).
> Jadi frame digambar apa adanya, tanpa konversi.

---

## Keputusan 2 — Alpha premultiplied

OBS menyusun scene dengan
`gs_blend_function_separate(ONE, INVSRCALPHA, ONE, INVSRCALPHA)` — operator "over"
premultiplied. Jadi kanal warna yang keluar dari Spout Filter **sudah dikalikan alpha**.

`Frame.premultiplied` membawa informasi ini, dan `OverlayWindow` memilih format QImage
berdasarkan pasangan `(pixel_format, premultiplied)`:

| Sumber | Format piksel | Format QImage |
|---|---|---|
| Spout dari OBS | RGBA8888 | `Format_RGBA8888_Premultiplied` |
| NDI | BGRA8888 | `Format_ARGB32` (straight, sesuai spesifikasi NDI) |
| Tangkapan layar | RGBA8888 | `Format_RGBA8888` (selalu opaque) |
| Berkas gambar | RGBA8888 | `Format_RGBA8888` |
| Pola uji bawaan | RGBA8888 | `Format_RGBA8888` |

Salah memilih di sini bukan kesalahan halus: menganggap data premultiplied sebagai
straight membuat Qt mengalikan alpha untuk kedua kalinya, dan hasilnya **garis gelap di
setiap tepi antialias**. Setelannya tetap bisa diubah pengguna per sumber di tab Source
karena sender non-OBS (Resolume, TouchDesigner) bisa mengirim straight alpha, dan ada
pengirim NDI yang menyalahi spesifikasinya sendiri.

NDI menambah satu jebakan lagi: FourCC-nya bisa `BGRA` **atau** `BGRX`. Pada `BGRX` byte
keempat adalah padding, bukan alpha, dan isinya tidak dijamin apa pun — jadi kanal itu
dipaksa 255. Tanpa itu, frame opaque bisa datang sebagai frame yang hilang seluruhnya.

---

## Keputusan 3 — Mask 1-bit, clip antialias

Dua produk berbeda dibuat dari daftar parsel yang sama:

- **`build_path()`** → `QPainterPath`, dipakai untuk *meng-clip lukisan*. Antialias, jadi
  parsel bulat dan elips punya tepi halus.
- **`build_region()`** → `QRegion`, diberikan ke `QWidget.setMask()`. Mask Windows itu
  1-bit: piksel dipertahankan atau dibuang, tidak ada di antaranya.

Region sengaja **dilebarkan 1 piksel** relatif terhadap path, supaya mask tidak memotong
tepi antialias yang sudah digambar painter. Hasilnya tepi lembut di atas apa pun yang ada
di belakang, bukan tangga piksel.

Untuk tata letak yang seluruhnya persegi ada jalur cepat: `QRegion` disusun langsung dari
`QRect`, menghasilkan segelintir rectangle alih-alih ratusan hasil dekomposisi scanline
dari bitmap. Ini penting karena Windows menelusuri daftar itu pada setiap hit test.

> PyQt6 menghapus `QRegion.rects()` dan `QRegion` tidak bisa di-iterate — hanya ada
> `rectCount()` dan `setRects()`. Karena itu daftar parsel selalu jadi sumber kebenaran;
> region tidak pernah dibaca balik.

---

## Keputusan 4 — Buffer pool dan latest-wins

Satu frame 1920×1080 RGBA = 8 MB. Mengalokasikannya setiap frame pada 60 FPS berarti
500 MB/detik lewat allocator.

Karena itu thread penerima meminjam buffer dari **pool berukuran tetap** (3 buffer), dan
thread GUI mengembalikannya setelah selesai melukis. Aturannya: satu pemilik pada satu
waktu. Kalau pool habis, producer **membuang** frame alih-alih memblokir — frame telat
lebih tidak berguna daripada frame segar.

Publikasi memakai **latest-wins**: kalau thread GUI belum mengambil frame sebelumnya saat
frame baru datang, yang lama dilepas dan dihitung sebagai drop. Mengantre frame hanya
menukar latensi dengan kehalusan yang tidak bisa dilihat siapa pun pada overlay.

`QImage` dibuat sebagai **view** ke memori pool (`QImage(bytearray, w, h, stride, fmt)`
tidak menyalin), jadi frame harus tetap hidup selama gambarnya masih dipakai — itulah
kenapa `OverlayWindow` memegang keduanya dan melepas yang lama hanya setelah yang baru
terpasang.

---

## Keputusan 5 — Konteks OpenGL diurus SpoutGL sendiri

`SpoutGL` butuh konteks WGL yang aktif di thread pemanggil: `spoutGL::OpenSpout()`
memanggil `wglGetCurrentDC()` dan gagal kalau tidak ada.

Alih-alih menambah dependensi (glfw/pygame) atau membuat `QOffscreenSurface`, aplikasi ini
memakai `receiver.createOpenGL()` yang memang disediakan untuk ini: fungsi itu membuat
jendela tersembunyi berkelas `BUTTON`, konteks WGL, lalu `wglMakeCurrent` **di thread
pemanggil**.

Konsekuensinya: **seluruh siklus hidup source harus berada di satu thread**. Karena itu
`FrameProducer` memiliki source-nya dari `open()` sampai `close()` dan tidak pernah
menyerahkannya ke thread lain.

---

## Keputusan 6 — Hotkey terikat thread, bukan window

`RegisterHotKey` dipanggil dengan HWND `NULL`, sehingga `WM_HOTKEY` masuk ke antrean pesan
**thread**, bukan ke jendela tertentu.

Alasannya: Qt menghancurkan dan membuat ulang native window pada beberapa operasi yang
tampak sepele (`setWindowFlags`, `setParent`, perpindahan layar). Hotkey yang terikat HWND
akan diam-diam berhenti bekerja setelahnya.

Pesan thread tetap sampai karena event dispatcher Qt di Windows menarik antrean dengan
`PeekMessage` dan meneruskannya ke setiap `QAbstractNativeEventFilter` dengan tipe
`windows_generic_MSG`.

---

## Keputusan 7 — Yang sengaja *tidak* disentuh di Win32

Qt sudah memasang `WS_EX_LAYERED` sendiri untuk jendela translucent frameless. Karena itu
`Win32WindowController`:

- hanya membalik tiga bit yang benar-benar miliknya — `WS_EX_TRANSPARENT`,
  `WS_EX_TOOLWINDOW`, `WS_EX_NOACTIVATE` — dengan read-modify-write, dan **tidak pernah**
  menghapus `WS_EX_LAYERED`;
- **tidak pernah** memanggil `SetLayeredWindowAttributes`. MSDN menyatakan bahwa setelah
  fungsi itu dipanggil, `UpdateLayeredWindow` akan gagal sampai bit layered dihapus dan
  dipasang ulang — yang berarti alpha per-piksel Qt mati permanen;
- selalu memanggil `SetWindowPos(..., SWP_FRAMECHANGED)` setelah mengubah ex-style, karena
  Windows menyimpan data frame di cache;
- menghilangkan `SWP_NOZORDER` **hanya** saat menegakkan topmost (MSDN: `HWND_TOPMOST`
  hanya dihormati kalau Z-order boleh berubah), dan menyertakannya saat sekadar
  menyegarkan style.

Toggle click-through memakai `SetWindowLongW`, bukan `QWidget.setWindowFlags()`, karena
yang terakhir memanggil `setParent()` secara internal: HWND dibuat ulang, widget
disembunyikan, dan semua yang terikat HWND lama hilang.

`WDA_EXCLUDEFROMCAPTURE` dijaga di balik pemeriksaan build ≥ 19041. Pada build lebih lama
Windows diam-diam menurunkannya ke `WDA_MONITOR`, yang membuat overlay jadi **kotak hitam
pekat** di setiap rekaman — lebih buruk daripada tidak melakukan apa-apa.

---

## Keputusan 8 — Konfigurasi yang tahan banting

`Profile.from_dict()` bersifat **total**: apa pun JSON yang masuk — rusak, terpotong, atau
jahat — selalu menghasilkan objek yang bisa dipakai, dengan nilai di luar jangkauan
dijepit dan nilai tak dikenal diganti default. File profil yang rusak tidak boleh membuat
aplikasi gagal start; file itu dikarantina (`.corrupt`) dan diganti yang baru.

Penulisan bersifat **atomik**: tulis ke file sementara di direktori tujuan, `flush`,
`fsync`, lalu `os.replace`. Mati listrik menyisakan file lama atau file baru, tidak pernah
yang setengah jadi. Ini penting karena menggeser parsel memicu penyimpanan (dengan
debounce 1 detik).

---

## Keputusan 9 — numpy + QImage, bukan OpenCV

Blueprint menyebut `cv2` **atau** Pillow sebagai opsi pemrosesan. Keduanya tidak dipakai:

- Pemrosesan piksel yang benar-benar dibutuhkan hanya pembuatan pola uji, dan numpy sudah
  cukup.
- Kompositing dan penskalaan dikerjakan `QPainter`, yang sudah dioptimalkan dan
  terintegrasi dengan backing store.
- `opencv-python` (versi non-headless) menautkan Qt-nya sendiri. Mencampurnya dengan PyQt6
  bisa menghasilkan plugin platform Qt ganda dan galat "Could not load the Qt platform
  plugin".

Hasilnya bundle jauh lebih kecil dan satu sumber kebenaran untuk rendering.

---

## Keputusan 10 — Tangkapan layar ditarik, bukan didorong

`QScreen.grabWindow()` tidak aman dipanggil dari thread pekerja, tapi `VideoSource.capture()`
justru selalu dipanggil dari thread producer. Ada dua cara keluar, dan yang jelas justru
salah:

- **Memblokir producer pada thread GUI** (`BlockingQueuedConnection`) akan **deadlock**.
  `FrameProducer.stop()` berjalan di thread GUI dan menunggu worker selesai; kalau worker
  saat itu sedang menunggu thread GUI, keduanya menunggu selamanya.
- **Menarik, bukan mendorong** — yang dipakai. `_ScreenGrabber` hidup di thread GUI dengan
  `QTimer` miliknya sendiri, menaruh `QImage` terbaru di balik `QMutex`, dan
  `ScreenSource.capture()` sekadar mengambil apa yang ada. Tidak ada yang pernah menunggu
  siapa pun.

`QImage` bersifat implicitly shared, jadi publikasi hanya menaikkan refcount: lock dipegang
dalam hitungan mikrodetik, tidak pernah selama penyalinan.

`QTimer` grabber sengaja dibuat di dalam slot `start()`, bukan di `__init__`, karena timer
harus dimiliki thread yang akan menjalankannya — dan `__init__` berjalan di thread
producer. Perintah start/stop dikirim `QMetaObject.invokeMethod(...)` dengan
`QueuedConnection`, tidak pernah blocking, dengan alasan yang sama seperti di atas.

Laju grab dibatasi 120 fps apa pun isi profil. Tangkapan desktop mahal dan tidak ada yang
butuh di atas refresh layar.

---

## Keputusan 11 — Notifikasi dan repaint di-coalesce

Producer memberi tahu thread GUI lewat signal `frameAvailable`, dan signal antar-thread
jadi *posted event*. Kalau producer memancarkannya per frame sementara GUI sedang sibuk,
antrean event tumbuh tanpa batas — dan antrean yang penuh membuat Qt kelaparan menjalankan
timer, termasuk timer yang dibutuhkan untuk melukis.

Karena itu dua hal digabungkan:

- **`FrameProducer._publish()`** hanya memancarkan `frameAvailable` kalau tidak ada
  notifikasi yang masih menunggu. `take_frame()` membersihkan tanda itu. Frame terbarunya
  tetap latest-wins; yang dibatasi cuma jumlah sinyalnya.
- **`OverlayWindow.request_repaint()`** menelan `update()` berulang selama satu repaint
  masih tertunda. `paintEvent` membersihkan tanda itu lebih dulu, sebelum melukis, supaya
  perubahan yang datang saat melukis tetap memicu repaint berikutnya.

Keduanya mengubah *laju notifikasi*, bukan isi datanya: frame yang dilihat pengguna selalu
yang paling baru.

---

## Threading

| Thread | Milik | Tugas |
|---|---|---|
| GUI | `QApplication` | Semua widget, semua `paintEvent`, semua mutasi profil, `_ScreenGrabber` |
| Producer | `FrameProducer(QThread)` | Konteks WGL, `VideoSource`, pacing |

Penyeberangan antar-thread cuma tiga, semuanya lewat mekanisme Qt:

- `frameAvailable` → GUI memanggil `take_frame()` (dilindungi `QMutex`, di-coalesce)
- `statusChanged` / `failed` → GUI memperbarui panel, tray, dan HUD
- `_ScreenGrabber.take()` → producer mengambil `QImage` terbaru (dilindungi `QMutex`)

Tidak ada widget yang pernah disentuh dari thread producer. `_ScreenGrabber` bukan widget,
dan satu-satunya yang menyentuhnya dari thread producer adalah `take()` yang dikunci; semua
sisanya dijalankan lewat slot di thread GUI.

`FrameProducer` menyimpan **salinan** `SourceSettings` (`deepcopy`), bukan referensi ke
objek profil. Kalau tidak, `_needs_reopen()` akan membandingkan sebuah objek dengan dirinya
sendiri — profil sudah berubah di tempat sebelum perbandingan sempat terjadi — dan
mengganti nama sender tidak akan pernah memicu sambung ulang.

---

## Kenapa semuanya bisa diuji

378 tes berjalan di Linux tanpa GPU, tanpa OBS, tanpa Windows:

- **Matematika editor** murni fungsi atas `RectSpec` → diuji langsung.
- **Parser hotkey** dipisah dari `ctypes` ke `hotkey_spec.py` → diuji di mana saja.
- **Lapisan native** punya implementasi Null yang jujur melaporkan "tidak didukung".
- **Sumber uji bawaan** memberi pipeline frame yang nyata tanpa perangkat keras.
- **Qt** berjalan dengan platform plugin `offscreen`, sehingga masking, rendering, dan
  interaksi editor benar-benar dieksekusi, bukan hanya di-mock. Ini juga berarti
  **tangkapan layar dan berkas gambar bisa diuji sungguhan** — keduanya cuma butuh Qt.
- **Sumber yang butuh perangkat keras atau jaringan** (Spout, NDI) diuji sampai batas yang
  jujur: konstruksi, pesan kegagalan, dan pilihan format. Jalur penerimaannya sendiri tidak
  pernah dijalankan di CI, dan docstring modulnya menyatakan itu apa adanya alih-alih
  berpura-pura sudah terbukti.
