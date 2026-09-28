# Hotkey

Semua hotkey di sini bersifat **global**: berfungsi walaupun aplikasi lain sedang fokus.
Semuanya bisa diubah di panel kontrol, tab **Hotkeys**.

## Bawaan

| Aksi | Kombinasi | Keterangan |
|---|---|---|
| Buka/tutup editor tata letak | `Ctrl+Alt+M` | Melepas mask dan menerima klik selama editor aktif |
| Aktif/nonaktifkan click-through | `Ctrl+Alt+C` | |
| Tampil/sembunyikan overlay | `Ctrl+Alt+H` | |
| Tampil/sembunyikan panel kontrol | `Ctrl+Alt+P` | |
| Muat ulang profil dari disk | `Ctrl+Alt+R` | Membuang perubahan yang belum tersimpan |
| **Panic** | `Ctrl+Alt+Shift+F9` | Kembalikan input, tampilkan overlay, keluar dari editor, buka panel |

Kombinasi bawaan dipilih untuk menghindari bentrok dengan OBS dan game yang umum.

## Aturan

**Harus ada modifier.** Kombinasi tanpa `Ctrl`, `Alt`, `Shift`, atau `Win` ditolak —
hotkey global tanpa modifier akan menelan tombol itu di seluruh sistem.

**F12 tidak bisa dipakai.** Windows memesannya untuk debugger (`"The F12 key is reserved
for use by the debugger at all times"`), dan `RegisterHotKey` menolaknya. Aplikasi akan
memberi tahu alih-alih diam saja.

**Auto-repeat dimatikan.** Semua registrasi memakai `MOD_NOREPEAT`, jadi menahan tombol
tidak memicu aksi berkali-kali per detik.

## Kalau registrasi gagal

Kalau kombinasi sudah dipakai proses lain, Windows mengembalikan
`ERROR_HOTKEY_ALREADY_REGISTERED`. Aplikasi menampilkan alasannya tepat di bawah kolom
hotkey yang bersangkutan, misalnya:

```
Ctrl+Alt+M is already used by another application.
```

Hotkey lain tetap terdaftar — satu kegagalan tidak membatalkan yang lain.

Kalau aplikasi yang memegangnya berjalan **sebagai administrator** sementara overlay
tidak, Windows juga tidak akan mengirimkan inputnya. Jalankan overlay dengan hak yang sama,
atau pilih kombinasi lain.

## Sintaks penulisan

Kalau Anda mengedit berkas profil secara manual, formatnya:

```
Ctrl+Alt+M
Ctrl+Shift+F9
Win+Space
Ctrl+Numpad5
Ctrl+Left
Ctrl++          (Ctrl dan tombol plus)
```

Nama modifier: `Ctrl` / `Control` / `Ctl`, `Alt`, `Shift`, `Win` / `Super` / `Meta` / `Cmd`.
Urutan bebas — semuanya dinormalkan ke `Ctrl+Alt+Shift+Win+<tombol>`.

Nama tombol yang dikenali: `A`–`Z`, `0`–`9`, `F1`–`F24`, `Numpad0`–`Numpad9`, `Space`,
`Tab`, `Enter`, `Esc`, `Backspace`, `Delete`, `Insert`, `Home`, `End`, `PageUp`,
`PageDown`, `Left`, `Right`, `Up`, `Down`, `Pause`, `PrintScreen`, `NumLock`,
`ScrollLock`, serta simbol `; = , - . / \` [ ] '` dan `+`.

## Shortcut di dalam mode editor

Yang berikut ini **bukan** hotkey global — hanya berlaku saat mode editor aktif dan
overlay sedang fokus.

| Aksi | Tombol |
|---|---|
| Geser 1 px | Panah |
| Geser satu grid | `Shift` + panah |
| Kunci rasio saat resize | Tahan `Shift` |
| Resize dari tengah | Tahan `Alt` |
| Buat parsel baru | `Ctrl` + seret |
| Tambah/kurangi seleksi | `Shift` + klik |
| Pilih semua | `Ctrl+A` |
| Duplikat | `Ctrl+D` |
| Hapus | `Delete` / `Backspace` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Shift+Z` atau `Ctrl+Y` |
| Naikkan urutan | `Ctrl+]` (dengan `Shift`: paling depan) |
| Turunkan urutan | `Ctrl+[` (dengan `Shift`: paling belakang) |
| Kosongkan seleksi, lalu keluar | `Esc` |
