# TikTok Follow Checker

Tool nay viet bang Python thuan va chay duoc tren Windows va macOS.

Tool doc thong tin public tren trang profile TikTok va liet ke:

- So follower
- So following
- So like
- Trang thai private / verified

Khong can API key, khong can cai them thu vien ngoai.

## Yeu cau

- Python 3.9 tro len

## Giao dien desktop

Windows:

```bash
python check_follow_gui.py
```

macOS:

```bash
python3 check_follow_gui.py
```

Build app cho macOS:

```bash
chmod +x build_mac.sh build_mac.command
./build_mac.sh
```

File app sau khi build:

```bash
dist/TikTokFollowChecker.app
```

Neu muon build bang double-click tren Mac:

1. Chay 1 lan trong Terminal de cap quyen:

```bash
chmod +x build_mac.sh build_mac.command
```

2. Sau do double-click file:

```bash
build_mac.command
```

File `.command` se:

- tu build app
- mo thu muc `dist`
- giu cua so Terminal lai de ban xem log

GitHub Actions:

- Repo da co workflow tai `.github/workflows/build-macos.yml`
- Khi push len nhanh `main` hoac chay tay bang `workflow_dispatch`, GitHub se build ban macOS
- Artifact tai ve se la `TikTokFollowChecker-macOS.zip`

Tinh nang da toi uu:

- Tao nhieu project khac nhau
- Moi project luu rieng danh sach user va ket qua check gan nhat
- Co nut `Add Users` de them user hang loat vao project hien tai
- Tu dong luu project sau khi ban sua danh sach user
- Hien tong so user va tong so ket qua ngay tren giao dien
- Bam `Check` de quet
- Bam `Load File` de nap file `.txt`
- Bam `Export CSV` de xuat ket qua

Khi ban check trong giao dien:

- Neu chua co project, tool se yeu cau tao project de luu danh sach do
- User cua project se duoc luu lai trong thu muc `projects/`
- Mo lai tool van thay duoc cac project cu

Voi ban build macOS `.app`, du lieu project se duoc luu tai:

```bash
~/Documents/TikTokFollowChecker/projects
```

Trong app co them nut `Open Data Folder` de mo nhanh thu muc nay.

## Command line

Windows:

```bash
python check_follow.py tiktok
```

macOS:

```bash
python3 check_follow.py tiktok
```

Chay nhieu user:

```bash
python check_follow.py user81103554418434 user8714072904381 user3014554047541
```

Doc danh sach tu file:

```bash
python check_follow.py --file users.example.txt
```

Nhap user hang loat ngay trong tool:

```bash
python check_follow.py --interactive
```

Sau do paste danh sach, moi dong 1 user, roi nhan Enter o dong trong de bat dau check.

Neu ban chay khong truyen tham so, tool se uu tien cho ban nhap truc tiep trong terminal. Neu khong nhap gi, no moi thu doc `users.txt`, sau do den `users.example.txt`.

In ket qua JSON:

```bash
python check_follow.py --json --file users.example.txt
```

## Dinh dang input

Tool chap nhan:

- `@username`
- `username`
- `https://www.tiktok.com/@username`

Neu ban dung PowerShell va muon nhap `@username` truc tiep, hay dat trong dau nhay, vi du: `"@tiktok"`.

Trong file text, moi dong la 1 user. Dong trong va dong bat dau bang `#` se bi bo qua.

## Ghi chu

- Tool nay doc du lieu public duoc nhung san trong HTML profile cua TikTok.
- Neu TikTok doi cau truc trang, tool co the can cap nhat lai parser.
- Mot so tai khoan bi khoa, bi chan, hoac bi gioi han truy cap co the khong lay duoc du lieu.
- Ban macOS build moi se kem CA bundle de tranh loi `SSL: CERTIFICATE_VERIFY_FAILED`.
- Ban macOS moi se luu project vao `Documents` de de thay va de tranh loi quyen ghi.
