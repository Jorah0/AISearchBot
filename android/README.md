# Lodestar for Android

A small native app that opens **your own Lodestar** on your phone: over your home Wi-Fi, or when the phone is
tethered to the computer (USB tethering or the phone's hotspot). Everything still runs on your computer; the app only
shows it. No third-party libraries, no account, no cloud.

## Install

1. On the computer: Lodestar > **Setup > Phone access** > **Turn on phone access**. It lists the addresses it listens on
   (your Wi-Fi one, and a tether's once one is up). Windows may ask to allow it through the firewall: allow it on
   private networks.
2. Copy `android\lodestar.apk` to the phone (USB, or email it to yourself) and open it. Android asks to allow installing
   from that app once.
3. Open **Lodestar** on the phone: type the address Setup shows (for example `192.168.1.153:8780`), or tap
   **Find Lodestar on this network**.
4. Back on the computer: **New pairing code**. Type the code on the phone. The phone stays paired until you choose
   **Sign out all phones** (computer) or **Forget this computer** (phone menu).

## What it does and does not do

- Loads only private addresses (10.x, 172.16-31.x, 192.168.x, `.local`). Any other link opens in your browser.
- Keys, passwords, sign-in codes, mail sign-in, backups, restore and updates are refused from a phone (the computer
  enforces this, not the app).
- Uploads (resume import, attachments) use the phone's file picker; downloads of Lodestar files go to Downloads.
  Files the computer builds in the browser (some exports) are saved from the computer.
- Plain HTTP on your own network, like the browser version: use it at home or on your own tether, not on public Wi-Fi.

## Build

Needs JDK 17, the Android SDK (platform 35, build-tools) and Gradle 8.9 under `%USERPROFILE%\Android` (`jdk`, `sdk`,
`gradle`), or `JAVA_HOME` / `ANDROID_HOME` / `GRADLE` set.

```powershell
powershell -ExecutionPolicy Bypass -File android\build.ps1        # android\lodestar.apk
powershell -ExecutionPolicy Bypass -File android\build.ps1 -Test  # + unit tests (AddressTest) and lint
```

The APK is debug-signed (installable on your own phone; not for a store). Debug builds allow WebView debugging over
USB so the end-to-end test can drive the page; a release build would not.
