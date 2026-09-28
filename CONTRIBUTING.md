# Berkontribusi

## Menyiapkan lingkungan

```bash
git clone https://github.com/yusril1701/obs-overlay.git
cd obs-overlay

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Di Linux, Qt headless butuh beberapa pustaka sistem:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libdbus-1-3 libfontconfig1
```

## Menjalankan pemeriksaan

```bash
pytest                      # seluruh tes
pytest -m "not gui"         # lewati tes yang butuh QApplication
ruff check src tests
ruff format src tests
mypy
```

Semuanya harus hijau sebelum mengirim perubahan. Tes berjalan di Linux tanpa GPU, tanpa
OBS, dan tanpa Windows — itu disengaja dan harus dipertahankan.

## Menjalankan aplikasi

```bash
python run.py --demo          # pola uji bawaan, tanpa perlu OBS
python run.py --log-level DEBUG
```

## Aturan lapisan

Batasan ini yang membuat sebagian besar kode bisa diuji. Tolong jangan dilanggar:

| Modul | Boleh mengimpor |
|---|---|
| `core/geometry.py` | stdlib + `config.models` saja. **Tidak boleh Qt.** |
| `config/` | stdlib saja. **Tidak boleh Qt.** |
| `native/hotkey_spec.py` | stdlib saja. **Tidak boleh `ctypes`.** |
| `native/` | Qt boleh, `ui/` tidak boleh |
| `ui/` | apa saja |

Kode khusus Windows harus punya pasangan no-op di `native/base.py`, supaya aplikasi tetap
bisa diimpor dan dijalankan di platform lain.

## Gaya

- `from __future__ import annotations` di setiap berkas (target runtime Python 3.9).
- Docstring dan komentar dalam bahasa Inggris; teks yang dilihat pengguna dan dokumentasi
  dalam bahasa Indonesia.
- Komentar menjelaskan **kenapa**, bukan **apa**. Kalau sebuah keputusan berlawanan dengan
  intuisi, jelaskan alasannya — beberapa di antaranya ada di `docs/ARCHITECTURE.md`.
- ruff yang menentukan format; jangan berdebat soal spasi.

## Menambah tes

- Logika murni → `tests/test_geometry.py`, `tests/test_config_models.py`
- Hal yang butuh Qt → tandai `@pytest.mark.gui`
- Hal yang butuh Windows → tandai `@pytest.mark.windows`

Tes yang butuh GPU, OBS, atau Spout sungguhan tidak akan bisa dijalankan CI. Kalau sebuah
perilaku hanya bisa diverifikasi di perangkat keras nyata, catat itu di docstring-nya.

## Mengubah skema profil

1. Naikkan `PROFILE_SCHEMA_VERSION` di `constants.py`.
2. Tambahkan langkah migrasi di `config/migrations.py`.
3. Tambahkan tes yang memuat berkas versi lama dan memeriksa hasilnya.

Berkas profil yang ditulis versi lama harus **selalu** tetap bisa dimuat.

## Melaporkan bug

Sertakan versi Windows, versi OBS, versi plugin Spout2, keluaran `--list-senders`, dan
potongan log yang relevan (`--log-level DEBUG`). Lihat
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
