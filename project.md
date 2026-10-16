project.md — AUDIT, PATCH, HEREDOC, TEST

# 12. STANDARD AUDIT PROCEDURE





Prinsip patch

Tidak melakukan perubahan hanya karena ada sesuatu yang terlihat kurang bagus.

Setiap patch harus punya bug/deficiency yang terbukti.

Sebelum patch harus ada baseline test.

Backup source terlebih dahulu.

Patch sekecil mungkin.

Tidak mengubah arsitektur kalau belum diperlukan.

Tidak memperbaiki satu masalah dengan mengorbankan behavior yang sudah PASS.

Setelah patch wajib:

syntax/compile test

internal unit/integration test yang relevan

regression test

audit log

compare hasil sebelum/sesudah

Jika hasil lebih buruk atau ada regression → rollback, bukan dipaksakan.

Patch yang tidak meningkatkan kualitas secara terukur → jangan dipertahankan.

Jangan menghapus backup/history sebelum perubahan terbukti stabil.

Source of truth tetap source terbaru + project.md + bukti runtime/log.





Semua debugging Hermes wajib mengikuti urutan:





SOURCE

→ AUDIT

→ HYPOTHESIS

→ VERIFY

→ SMALL PATCH

→ SYNTAX CHECK

→ RUNTIME TEST

→ LOG AUDIT

→ COMPARE

→ CHANGELOG





Tidak boleh langsung patch sebelum titik masalah teridentifikasi.





---





# 13. AUDIT RULE





## 13.1 Source dulu





Sebelum membuat hipotesis, baca source aktif.





Gunakan:





```bash

nl -ba <file> | sed -n 'START,ENDp'
```

atau:

```bash
grep -n -B5 -A10 "<target>" <file>
```

Jangan menggunakan file .bak sebagai source aktif kecuali memang sedang melakukan comparison.



## 13.2 Audit harus berbasis bukti



Setiap hipotesis harus memiliki bukti.



Format:



HYPOTHESIS:

<dugaan>





EVIDENCE:

<source/log>





TEST:

<cara membuktikan>





EXPECTED:

<hasil yang diharapkan>



Contoh:



HYPOTHESIS:

592 facts berasal dari beberapa research node.





EVIDENCE:

all_facts menggabungkan semua node found/verified.





TEST:

log jumlah requirements dan facts per node.





EXPECTED:

node A=21, node B=..., node C=...

# 14. AUDIT DATA FLOW



Untuk bug pipeline, audit harus mengikuti aliran data:



REQUEST

  ↓

ROUTER

  ↓

PLANNER

  ↓

REQUIREMENTS

  ↓

SEARCH

  ↓

FETCH

  ↓

EVIDENCE

  ↓

EXTRACT

  ↓

RANK

  ↓

KG

  ↓

ALL_FACTS

  ↓

SYNTHESIS

  ↓

ANSWER



Pada setiap titik, ukur:



count

identity/topic

source

status



Jangan hanya melihat output akhir.



# 15. INSTRUMENTATION RULE



Instrumentation harus:



hanya menambah observability

tidak mengubah business logic

tidak mengubah result

tidak mengubah ranking

tidak mengubah prompt

tidak mengubah limit

tidak mengubah control flow



Contoh yang benar:



logger.info(

    "[AUDIT NODE] topic=%s facts=%d",

    topic,

    len(facts),

)



Contoh yang salah:



facts = facts[:20]



karena itu sudah mengubah behavior.



# 16. PATCH WAJIB MENGGUNAKAN HEREDOC

Gunakan Python heredoc dengan exact target block sesuai contoh lengkap bagian 37.
Backup terpusat harus dibuat dan diverifikasi sebelum write. Target wajib ditemukan
tepat satu kali (count == 1), lalu write sekali. Jangan membuat backup di samping source aktif.

# 17. HEREDOC PATCH RULE



Patch script wajib:



membuat backup

mencari exact block

memastikan block ditemukan

memastikan block hanya muncul satu kali

mengganti hanya satu block

gagal dengan jelas jika target tidak cocok

mencetak PATCH OK

mencetak lokasi backup



Jangan menggunakan:



sed -i



untuk patch logic kompleks.



Jangan melakukan replace berdasarkan potongan terlalu umum seperti:



text.replace("return result", ...)



karena dapat mengenai lokasi yang salah.



# 18. JIKA PATCH GAGAL



Jika muncul:



PATCH GAGAL



JANGAN mencoba patch dengan tebakan kedua.



Lakukan:



nl -ba <file> | sed -n 'START,ENDp'



atau:



grep -n -B10 -A15 "<target>" <file>



Kemudian cocokkan source aktual.



Aturan:



PATCH GAGAL

→ BACA SOURCE AKTUAL

→ SESUAIKAN TARGET

→ PATCH ULANG



Bukan:



PATCH GAGAL

→ ubah script secara acak

# 19. SYNTAX CHECK



Setiap patch Python wajib:



python3 -m py_compile <file.py>



Expected:



(no output)



Jika gagal:



JANGAN restart server.

JANGAN lanjut test.

PERBAIKI syntax terlebih dahulu.

# 20. SOURCE DIFF SETELAH PATCH



Setelah patch:



git diff -- <file>



Jika repository tidak menggunakan git:



diff -u <backup> <file>



Tujuan:



memastikan patch hanya mengubah bagian yang dimaksud.



# 21. RUNTIME TEST



Setelah syntax check dan required offline tests berhasil, ikuti bagian 40–43.
Offline PASS bukan izin restart atau live acceptance.
Restart/reload hermes.service hanya setelah persetujuan eksplisit pengguna.

pastikan hanya instance yang benar berjalan

cek PID

lakukan satu test request

simpan log



Cek:



pgrep -af 'uvicorn api.main:app'



Jika ada beberapa instance Hermes:



STOP



dan tentukan instance mana yang aktif sebelum melakukan test.



# 22. TEST REQUEST



Gunakan satu query terkontrol.



Contoh utama:



spesifikasi acr 12500 black



Jangan menguji 5 query sekaligus setelah patch.



Tujuannya:



1 patch

→ 1 behavior

→ 1 test

# 23. TEST NEGATIVE / REGRESSION



Setelah test utama berhasil, lakukan regression minimal:



5+5



Expected:



direct

10



dan:



speaker acr 12500 black



Expected:



research



Kemudian gunakan satu entity berbeda untuk memastikan patch tidak hardcoded.



Contoh:



spesifikasi JBL PartyBox

# 24. LOG TEST

Saat test research, cari:

```bash
grep -nE '\[REQ|\[router\]|\[AUDIT|\[planner\]|\[SEARCH\]|\[FETCH\]|\[EXTRACT|\[rank\]|\[orchestrator\]|PROMPT SIZE|early stop' server.log | tail -200
```

Jika server dijalankan langsung di terminal, gunakan output terminal sebagai evidence.

# 25. AUDIT RESULT



Setelah test, catat:



TEST:

spesifikasi acr 12500 black





ROUTER:

research





PLAN:

requirements=N





SEARCH:

candidate count=N





FETCH:

count=N





EXTRACT:

count=N





RANK:

count=N





KG:

count=N





SYNTHESIS:

all_facts=N





PROMPT:

chars=N





ANSWER:

<ringkasan>



Tujuannya menemukan titik pertama ketika jumlah data melonjak.



# 26. DATA EXPLOSION RULE



Jika ditemukan:



21 facts

↓

592 facts



jangan langsung membatasi 592.



Cari titik pertama:



21

→ ?

→ ?

→ ?

→ 592



Contoh:



extract = 21

rank = 21

KG = 21



berarti node tersebut sehat.



Jika:



extract = 500

rank = 500



masalah ada sebelum/di extractor.



Jika:



extract = 21

rank = 500



ranker bermasalah.



Jika:



rank = 21

KG = 592



aggregation/persistence bermasalah.



Jika:



KG = 21

all_facts = 592



synthesis aggregation bermasalah.



# 27. EARLY STOP RULE



Jika log:



early stop: 592 facts



jangan menganggap 592 sebagai target.



Early stop hanya menunjukkan:



MAX_TOTAL_FACTS tercapai



Audit harus mencari kenapa jumlah tersebut tercapai.



Jangan menaikkan atau menurunkan MAX_TOTAL_FACTS sebagai patch pertama.



# 28. SEARCH NOISE RULE



Jika search menghasilkan:



official source

+

unrelated source



audit:



query

→ SearXNG raw results

→ _score_and_rank()

→ selected results

→ fetched URLs



Bandingkan count dan URL pada setiap tahap.



Jangan langsung blacklist domain tertentu.



# 29. EVIDENCE PRIORITY RULE



Untuk entity/product research:



official source

manufacturer

official datasheet/manual

reputable technical source

retailer

forum/social



merupakan prioritas evidence.



Tetapi prioritas tidak boleh diimplementasikan sebagai whitelist khusus satu brand.



Ranking harus general.



# 30. ANSWER VS PIPELINE RULE



Jika Open WebUI sudah menampilkan answer tetapi server masih logging:



jangan menganggap research sudah selesai.



Periksa:



REQ ID

iteration

node status

fetch activity

LLM calls

Open WebUI internal requests



Satu user interaction dapat menghasilkan request tambahan dari Open WebUI.



Bedakan:



user research request



dengan:



Open WebUI internal task

# 31. BACKUP RULE



Sebelum patch:



backup dibuat otomatis



Backup harus memiliki timestamp.



Contoh:



/home/arman/research-assistant/backup/patch_20260815_120000/hermes_agent/orchestrator.py



Jangan menghapus backup selama debugging aktif.



# 32. REVERT RULE



Jika patch memperburuk behavior:



cp <backup> <original>

python3 -m py_compile <original>



Kemudian test ulang.



Catat:



REVERTED



di CHANGELOG.



# 33. CHANGELOG RULE



Setiap patch dicatat:



DATE:

FILE:

PROBLEM:

HYPOTHESIS:

EVIDENCE:

PATCH:

TEST:

RESULT:

STATUS:



Status proses: HYPOTHESIS, REVERTED, atau OPEN.

Status implementasi/verifikasi: PATCHED, OFFLINE VERIFIED, ACTIVE, atau LIVE VERIFIED.
Definisi dan bukti wajib mengikuti bagian 41. Jangan memakai VERIFIED tanpa kualifikasi.
Laporkan status tertinggi yang benar-benar terbukti dan batas verifikasi yang masih OPEN.

Jangan menulis:



FIXED



jika belum ada regression test.



# 34. CHAT HANDOFF RULE



Jika pindah chat:



sertakan:



project.md

Hermes_Architecture.md

Hermes_Status.md

CHANGELOG.md



dan source aktif yang relevan.



Chat baru wajib:



membaca source

membaca status

membaca changelog

memahami last hypothesis

melanjutkan dari NEXT STEP



Tidak mengulang patch lama tanpa alasan.



# 35. CURRENT DEBUGGING PRIORITY



Masalah aktif:



21 ACR facts

→ 592 total facts



Prioritas:



[AUDIT PLAN]

[AUDIT NODE]

[AUDIT SYNTHESIS]



Setelah audit baru boleh menentukan patch.



Urutan:



AUDIT

→ FIND FIRST DATA EXPLOSION

→ ONE SMALL PATCH

→ HEREDOC

→ PY_COMPILE

→ DIFF

→ EXPLICIT USER APPROVAL FOR RESTART

→ RESTART

→ ONE TEST

→ LOG

→ REGRESSION

→ CHANGELOG





## Tambahkan juga ke `Hermes_Status.md`





```markdown

# DEBUGGING PROTOCOL





Current debugging must follow:





SOURCE

→ AUDIT

→ HYPOTHESIS

→ VERIFY

→ HEREDOC PATCH

→ PY_COMPILE

→ DIFF

→ EXPLICIT USER APPROVAL FOR RESTART

→ RESTART

→ SINGLE TEST

→ LOG AUDIT

→ REGRESSION

→ CHANGELOG





No logic patch is allowed before the relevant data-flow point is proven by source or runtime evidence.





Current unresolved case:





21 valid ACR facts → approximately 592 total facts.





Next action is instrumentation, not filtering.

```



Format kerja yang kita pakai mulai sekarang



Kalau nanti Anda kirim source/log, saya akan mengikuti pola:



1. BUKTI

2. HIPOTESIS

3. TITIK SOURCE

4. PATCH HEREDOC

5. PY_COMPILE

6. DIFF

7. RESTART (hanya setelah explicit user approval; bagian 40)

8. TEST

9. BACA LOG

10. KESIMPULAN

11. CHANGELOG



Kalau PATCH GAGAL, berhenti di situ dan minta/cek source aktual sebelum membuat heredoc baru.



---



# 36. PERMANENT BACKUP AND TEST LOCATION RULE



DATE:

2026-10-13



Bagian 36–43 merupakan tambahan permanen berdasarkan instruksi pengguna.

Jika aturan lokasi, Git, aktivasi, atau verifikasi di bagian lama berbeda, gunakan bagian 36–43.

Bagian 16 merujuk backup terpusat pada bagian 37; backup di samping source dilarang.

Bagian 37 menjadi contoh heredoc yang berlaku.



## 36.1 Backup patch



Sebelum setiap patch pada file yang sudah ada, termasuk dokumentasi:



backup source aktif terlebih dahulu

pastikan backup berhasil dan isinya sama dengan source sebelum patch

baru lakukan perubahan



Seluruh backup patch hanya boleh disimpan di:



```text

/home/arman/research-assistant/backup/

```



Backup wajib memiliki timestamp dan identitas file asal.

Gunakan subdirektori timestamp agar path relatif file asal tetap terlihat.



Contoh:



```text

/home/arman/research-assistant/backup/patch_20261013_143000_123456/hermes_agent/fact_checker.py

/home/arman/research-assistant/backup/patch_20261013_143000_123456/project.md

```



Jangan membuat .bak, .orig, atau salinan backup lain berdampingan dengan source.

Jangan menimpa backup yang sudah ada.

Jika direktori backup tidak dapat ditulis atau verifikasi backup gagal:



STOP



Jangan menghapus backup tanpa alasan yang terbukti dan dicatat.

Stabilnya patch saja bukan alasan otomatis untuk menghapus backup.

Jangan menghapus backup selama debugging aktif.

Backup bukan source aktif dan tidak ikut commit.



## 36.2 Test baru dan test lama



Seluruh test baru wajib dibuat di:



```text

/home/arman/research-assistant/tests/

```



Termasuk unit test, integration test, regression test, test harness, fixture,

dan script reproduksi yang dibuat sebagai test.

Gunakan subdirektori di dalam tests/ jika diperlukan.

Jangan membuat test baru di root repository atau berdampingan dengan source.



Jangan menghapus atau mengedit test lama hanya agar patch menjadi PASS.

Perubahan test lama hanya boleh dilakukan jika ada alasan yang terbukti:



kontrak behavior memang berubah dan perubahan itu disetujui

atau test lama terbukti salah berdasarkan source/kontrak dan evidence



Catat alasan, evidence, diff, dan hasil sebelum/sesudah.

Backup test lama ke backup/ sebelum perubahan.

Jika tidak ada alasan terbukti, pertahankan test lama dan tambahkan regression test baru di tests/.



---



# 37. HEREDOC PATCH WITH CENTRAL BACKUP



Contoh ini adalah prosedur heredoc dan backup terpusat yang dirujuk bagian 16.

Jalankan hanya setelah source aktif, baseline, dan target patch terverifikasi.

Isi path dan exact block sesuai source aktual.



```bash

python3 <<'EOF'

from pathlib import Path

from datetime import datetime, timezone

import shutil



root = Path('/home/arman/research-assistant').resolve()

p = (root / 'hermes_agent/fact_checker.py').resolve(strict=True)

relative = p.relative_to(root)

if relative.parts[0] in {'backup', '.git'}:

    raise SystemExit('PATCH GAGAL: target bukan source/test/dokumentasi aktif.')



text = p.read_text(encoding='utf-8')

old = '''OLD EXACT BLOCK'''

new = '''NEW EXACT BLOCK'''



if text.count(old) != 1:

    raise SystemExit(

        f'PATCH GAGAL: blok ditemukan {text.count(old)} kali, expected 1.'

    )



timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%fZ')

backup_root = root / 'backup'

backup_root.mkdir(exist_ok=True)

if backup_root.is_symlink():

    raise SystemExit('PATCH GAGAL: backup/ tidak boleh mengarah ke lokasi lain.')

backup_dir = backup_root / f'patch_{timestamp}'

backup_dir.mkdir(exist_ok=False)

backup = backup_dir / relative

backup.parent.mkdir(parents=True, exist_ok=True)

shutil.copy2(p, backup)



if backup.read_bytes() != p.read_bytes():

    raise SystemExit('PATCH GAGAL: isi backup berbeda dari source aktif.')

if p.read_text(encoding='utf-8') != text:

    raise SystemExit('PATCH GAGAL: source berubah sejak inspeksi; audit ulang.')



p.write_text(text.replace(old, new, 1), encoding='utf-8')

print('PATCH OK')

print('Backup:', backup)

EOF

```



Gunakan interpreter/virtualenv service aktif yang sudah diverifikasi jika berbeda dari python3.

Timestamp contoh script menggunakan UTC dengan suffix Z.

Jika backup atau patch gagal, berhenti dan baca source aktual.

Jangan menghapus backup yang telah berhasil dibuat.



---



# 38. SAFE COMMIT AND GITHUB MASTER SYNC PROCEDURE



## 38.1 Bedakan operasi dan persetujuan



```text

git fetch = mengambil informasi/object remote tanpa menggabungkan ke worktree

git pull  = mengambil dari remote lalu mengintegrasikan ke branch lokal

git push  = mengirim commit lokal ke remote

```



Pull bukan cara mengirim patch ke GitHub.

Commit menyimpan perubahan staged ke history lokal.



Wajib ada persetujuan eksplisit pengguna sebelum:



commit

push

pull



Persetujuan harus jelas untuk operasi, remote, branch, dan perubahan yang akan dijalankan.

Persetujuan commit tidak otomatis memberi izin push atau pull.

Instruksi audit, patch, test, atau memperbarui project.md bukan persetujuan operasi Git tersebut.

Siapkan hasil yang dapat ditinjau terlebih dahulu, lalu minta persetujuan sebelum eksekusi.

Jika persetujuan belum ada:



STOP sebelum commit/push/pull



Jangan force push. Jangan menggunakan --force-with-lease tanpa explicit approval
pengguna yang secara khusus menyebut operasi tersebut; approval push biasa tidak cukup.
Prosedur sinkronisasi normal di dokumen ini tidak mengizinkan force push.

Jangan menggunakan git reset untuk menimpa atau membuang pekerjaan, termasuk git reset --hard.

Jangan overwrite dirty worktree, melakukan checkout paksa, atau git clean.

Jangan stash, membuang perubahan, atau menyelesaikan konflik secara otomatis tanpa instruksi pengguna.



## 38.2 Inspeksi sebelum perubahan



Pastikan repository yang diperiksa adalah checkout Hermes yang dimaksud.

Periksa source yang benar-benar digunakan service, interpreter, dan instance aktif.

Jangan menganggap repository HEAD atau file backup adalah source runtime aktif.



```bash

cd /home/arman/research-assistant

git rev-parse --show-toplevel

git branch --show-current

git status --short --branch

git diff --stat

git diff

git diff --check

git diff --cached --stat

git diff --cached

git ls-files --others --exclude-standard

```



Periksa remote dan URL fetch/push secara lokal; jangan menyalin token/credential ke laporan.

Pastikan target adalah repository GitHub yang benar dan branch master memang tersedia.

Jangan menganggap origin selalu menunjuk repository yang dimaksud.



Catat baseline, file yang sudah berubah, perubahan staged, dan file untracked.

Bedakan pekerjaan sebelumnya dengan perubahan untuk patch ini.

Backup file yang akan dipatch sesuai bagian 36 sebelum perubahan.

Jika patch menyentuh tests/ atau project.md yang sudah ada, backup file itu juga.



## 38.3 Compile, test, regression, dan bukti



Sebelum commit:



syntax/compile check untuk Python yang berubah

unit/integration test yang relevan dengan interpreter service aktif

reproduksi bug sebelum/sesudah

regression test untuk behavior yang sebelumnya PASS

runtime test dan audit log bila perubahan memengaruhi runtime

compare hasil dan source diff

catat hasil di CHANGELOG sesuai bagian 33



Test baru mengikuti bagian 36.2.

Periksa exit code dan hasil test; jangan hanya melihat bahwa perintah selesai.

Jika test gagal, regression muncul, atau pemeriksaan wajib belum dapat dijalankan:



JANGAN COMMIT

JANGAN PUSH



Perbaiki penyebabnya atau lakukan rollback patch sesuai bagian 32 dari backup terverifikasi.

Jangan menggunakan reset, menghapus test, atau melemahkan assertion agar test PASS.

Perubahan dokumentasi saja diperiksa isi, konsistensi instruksi, Markdown, dan diff;

compile/runtime test tidak diperlukan jika source/test tidak berubah.

Catat pemeriksaan yang tidak relevan beserta alasannya.



## 38.4 File sensitif, staging, dan commit



Periksa seluruh file yang akan masuk commit, termasuk file baru/untracked.
Lakukan secret scan untuk password, API key, bearer token, SSH credential,
private key, dan session cookie nyata; laporkan file/baris/jenis tanpa nilai rahasia.
Test dengan credential nyata tidak commit-ready. Jangan sertakan artefak untracked
atau perubahan lain di luar scope yang telah ditinjau.

Jangan commit:



.env atau konfigurasi berisi credential

API key, token, password, private key

backup/, dump data privat, atau log berisi informasi sensitif

cache, virtualenv, dan output sementara test/runtime



Jangan tampilkan nilai rahasia dalam laporan atau output pemeriksaan.

Jangan mengubah .gitignore tanpa meninjau kebutuhan dan diff-nya.



Stage hanya path yang disengaja:



```bash

git add -- <path-yang-disetujui>

git diff --cached --name-status

git diff --cached --stat

git diff --cached --check

git diff --cached

```



Jangan git add . atau git add -A untuk patch terbatas.

Jika index sudah berisi pekerjaan lain, berhenti dan tentukan scope bersama pengguna.

Jangan memasukkan atau mengeluarkan pekerjaan lain dari index secara otomatis.

Pastikan setiap file staged, termasuk penghapusan file, memang termasuk scope commit.

Test harus memvalidasi isi yang akan di-commit; jika staged diff berubah, ulang pemeriksaan yang terdampak.



Sampaikan daftar file, ringkasan staged diff, hasil test, dan pesan commit yang diusulkan.

Setelah persetujuan eksplisit commit diterima, commit hanya staged diff yang telah ditinjau.

Jika scope berubah setelah persetujuan, tinjau ulang dan minta persetujuan untuk scope baru.

Setelah commit, periksa status dan commit yang terbentuk.



## 38.5 Fetch dan compare sebelum pull/push master



Contoh berikut memakai origin hanya setelah remote terverifikasi.

Perintah ini adalah prosedur untuk penggunaan berikutnya, bukan perintah otomatis.



```bash

git fetch --dry-run origin

git fetch origin

git rev-parse --verify refs/remotes/origin/master

git status --short --branch

git rev-list --left-right --count HEAD...origin/master

git log --oneline --left-right HEAD...origin/master

git diff --stat HEAD origin/master

```



Pada rev-list di atas:



angka kiri = commit lokal yang belum ada di origin/master

angka kanan = commit remote yang belum ada di HEAD lokal



Fetch tidak menjalankan pull atau push dan tidak memberi persetujuan untuk keduanya.

Jika remote/branch tidak cocok, fetch gagal, atau riwayat tidak dapat dibandingkan:



STOP



Jika worktree/index dirty, jangan pull atau push dalam prosedur ini.

Jangan membersihkan worktree secara paksa.

Selesaikan atau simpan pekerjaan melalui langkah yang disetujui pengguna.

Jika lokal dan remote divergen, laporkan perbedaannya dan minta keputusan integrasi.

Jangan merge/rebase/reset otomatis.



## 38.6 Pull dari master GitHub



Syarat:



branch lokal aktif adalah master

worktree dan index bersih

remote master sudah di-fetch dan dibandingkan

integrasi dapat dilakukan fast-forward

persetujuan eksplisit pull sudah diterima



Git pull tidak memiliki opsi --dry-run.

Gunakan fetch --dry-run, fetch, dan compare pada bagian 38.5 sebagai pemeriksaan awal.

Jangan mengklaim telah menjalankan pull dry-run.



Setelah seluruh syarat terpenuhi:



```bash

git pull --ff-only origin master

```



Jika fast-forward ditolak, berhenti dan inspeksi ulang.

Setelah pull, periksa status, diff commit yang masuk, dan source aktif.

Jalankan compile/test/regression yang terdampak sebelum restart/deploy atau push berikutnya.

Pull tidak otomatis mengubah proses service yang sedang berjalan.



## 38.7 Push ke master GitHub



Syarat:



branch lokal aktif adalah master

worktree dan index bersih

seluruh commit lokal yang akan dikirim sudah ditinjau

compile/test/regression yang relevan PASS

origin/master merupakan ancestor dari master lokal

remote dan target refs/heads/master terverifikasi



```bash

git merge-base --is-ancestor origin/master master

git log --oneline origin/master..master

git diff --stat origin/master master

git diff origin/master master

git push --dry-run origin master:refs/heads/master

```



Jika ancestor check atau dry-run gagal:



STOP



Dry-run tidak mengirim perubahan dan bukan izin push.

Sampaikan commit yang akan dikirim, diff, hasil test, serta hasil dry-run.

Setelah persetujuan eksplisit push diterima, fetch/compare ulang dan pastikan commit yang dikirim masih sama.

Jika remote atau scope berubah, tinjau ulang sebelum melanjutkan.



```bash

git push origin master:refs/heads/master

```



Jangan bypass branch protection atau memaksa push yang ditolak.

Jika push ditolak karena remote berubah, fetch/compare ulang dan laporkan; jangan force-push.

Setelah push, fetch dan verifikasi commit master remote sesuai commit yang disetujui.



---



# 39. PRE-COMMIT AND SYNC AUDIT RECORD



Simpan bukti yang dapat ditinjau sebelum meminta persetujuan operasi Git:



```text

DATE:

REPOSITORY / REMOTE:

LOCAL BRANCH / REMOTE BRANCH:

ACTIVE SOURCE / INTERPRETER:

BASELINE:

BACKUP PATH:

FILES IN SCOPE:

SOURCE DIFF:

COMPILE:

UNIT / INTEGRATION:

REGRESSION:

RUNTIME / LOG AUDIT:

SENSITIVE FILE CHECK:

STAGED DIFF:

FETCH / LOCAL-REMOTE COMPARE:

DRY-RUN:

REQUESTED OPERATION:

USER APPROVAL / SCOPE:

RESULT:

NEXT STEP:

```



Isi PASS/FAIL atau NOT APPLICABLE dengan alasan dan evidence.

Untuk perubahan dokumentasi, cantumkan pemeriksaan isi/Markdown/diff.

Jangan menulis approval sebagai APPROVED jika pengguna belum memberikannya.

Jangan menulis COMMITTED, PUSHED, atau PULLED sebelum operasi benar-benar berhasil.

Catat status patch menggunakan nilai yang diizinkan pada bagian 33.

---

# 40. SERVICE ACTIVATION AND RESTART APPROVAL

Offline test PASS does NOT authorize service restart. Restart/reload hermes.service
requires explicit user approval (persetujuan eksplisit pengguna), scoped to the
verified change and target service. Activation/deployment also requires approval;
audit, patch, compile, or test instructions alone do not grant it.
Do not restart unrelated services.

Before an approved restart/reload:

- Record the current PID and service state of hermes.service.
- Confirm the service working directory, entry point, interpreter, and active checkout.
- Ensure the source to activate matches the tested checkout and reviewed diff;
  record the revision and relevant uncommitted source differences.
- Require syntax/py_compile and all required offline tests/regressions to PASS first.

After restart/reload:

- Verify hermes.service is active and record the resulting PID (new PID on restart;
  a reload may retain the PID).
- Inspect startup/reload errors and correlated service logs.
- Report activation separately from behavioral acceptance; ACTIVE alone is not LIVE VERIFIED.

All earlier restart steps are conditional on this approval and these checks.
If activation fails, stop and report it; do not restart other services or silently
expand the approved scope.

# 41. VERIFICATION STATUS MODEL

| Status | Evidence and meaning |
|---|---|
| PATCHED | Source changed; sufficient evidence of correctness is not yet available. |
| OFFLINE VERIFIED | Compile/syntax and required offline tests PASS; production may still run old code. |
| ACTIVE | Verified source has been activated in the runtime/service; activation alone does not prove behavior. |
| LIVE VERIFIED | Controlled production/UI acceptance confirms expected behavior, supported by correlated runtime logs. |

- Never call a patch LIVE VERIFIED based only on unit tests or other offline checks.
- Never call HTTP 200 alone a behavioral PASS; inspect the actual result and trace.
- Report the highest status actually proven, with evidence, scope, and remaining OPEN checks.
- Do not skip required offline verification when reporting ACTIVE or LIVE VERIFIED.
- HYPOTHESIS, OPEN, and REVERTED describe process state, not stronger verification.
- For documentation-only work, report documentation validation separately;
  service activation and live acceptance are NOT APPLICABLE unless separately requested.

# 42. KG SAFETY FOR CONTROLLED LIVE ACCEPTANCE

Before any controlled live acceptance that may touch research/KG, record a read-only
snapshot of the actual KG used by that runtime. After acceptance, record the same
fields using the same counting definitions:

- KG file/path (resolved runtime path).
- SHA256 of the KG file bytes.
- node count.
- edge count.
- fact count.
- mtime_ns.

State how nodes, edges, and facts are counted from the current KG schema; do not
assume node count equals fact count. If a field cannot be measured, report it as
unavailable with the reason; do not invent a value or claim the safety check PASS.
If the file changes during snapshot capture, report the inconsistency and obtain
a stable read-only snapshot before interpreting before/after differences.

Report either unchanged (all recorded values match) or the exact delta: before/after
path, SHA256, counts, and mtime_ns, including count differences and relevant changed
records where inspectable. Explain expected versus unexpected changes; unrelated
concurrent activity must not be attributed to the acceptance request without evidence.

Do not silently modify, delete, or revert KG state. If unexpected mutation occurs,
stop, preserve evidence, and report it; restoration requires an explicit scoped decision.
If the test is intentionally isolated from KG, state the isolation explicitly,
identify the substituted in-memory/temporary store, and verify production KG writes
are bypassed. Report production before/after fingerprints when production KG safety
is part of the acceptance claim.

# 43. CONTROLLED LIVE ACCEPTANCE

- Run required offline tests and regressions first.
- Require explicit approval before activation/restart as defined in section 40.
  A documentation patch does not authorize activation or a live request.
- Begin with exactly one controlled request and defined expected behavior.
  Inspect that result and logs before any further live regression requests.
- Correlate request ID / event ID / model selection where available; report missing
  correlation fields and limits rather than assuming they match.
- Determine DIRECT versus RESEARCH from the actual runtime trace, not the prompt,
  assumed route, response wording, or HTTP status alone.
- For DIRECT, verify planner/search/evidence pipeline bypass when expected.
- For RESEARCH, verify research.status and its completeness/failure details
  separately from HTTP transport status; HTTP 200 can still contain a failed outcome.
- Apply section 42 before and after any acceptance that may touch research/KG.
- Do not force provider failure merely to prove retry behavior unless explicitly
  approved by the user. Use isolated offline failure tests otherwise.
- Report expected versus observed behavior, correlated logs, KG safety result,
  and the highest proven verification status. Leave unobserved acceptance OPEN.
