# Install on Windows without the app

Every step the setup app does, as commands. Use **PowerShell** (Start menu, type `PowerShell`). Run one block at a time and accept the Windows permission prompts.

## 1. Classic pack

### Programs

```powershell
winget install --id MSYS2.MSYS2 -e --accept-package-agreements --accept-source-agreements
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id Microsoft.VisualStudioCode -e --accept-package-agreements --accept-source-agreements
```

### GCC, GDB, CMake, Ninja, Make (inside MSYS2)

```powershell
$bash = "C:\msys64\usr\bin\bash.exe"
$env:MSYSTEM = "UCRT64"
& $bash -lc "pacman -Syu --noconfirm"
& $bash -lc "pacman -Syu --noconfirm"
& $bash -lc "pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-gdb mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-make"
```

`pacman -Syu` runs twice on purpose: the first run may only update MSYS2 itself.

### Put GCC on PATH

```powershell
$bin = "C:\msys64\ucrt64\bin"
$path = [Environment]::GetEnvironmentVariable("Path", "User")
# First, not last: Windows uses the first gcc.exe it finds, so an older MinGW would win.
$rest = ($path -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ne $bin }) -join ";"
[Environment]::SetEnvironmentVariable("Path", "$bin;$rest", "User")
```

**Close PowerShell and open a new one**, otherwise `gcc` is still not found.

### VS Code extensions

```powershell
code --install-extension ms-vscode.cpptools
code --install-extension ms-vscode.cmake-tools
```

## 2. Check it works

```powershell
gcc --version
g++ --version
cmake --version
Set-Content hello.cpp '#include <iostream>
int main() { std::cout << "Hello from C++!\n"; }'
g++ -std=c++20 -Wall hello.cpp -o hello.exe
.\hello.exe
```

You should see `Hello from C++!`.

## 3. Optional packs

**Code quality**

```powershell
& "C:\msys64\usr\bin\bash.exe" -lc "pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-clang-tools-extra mingw-w64-ucrt-x86_64-cppcheck mingw-w64-ucrt-x86_64-catch mingw-w64-ucrt-x86_64-gtest"
code --install-extension llvm-vs-code-extensions.vscode-clangd
code --install-extension usernamehw.errorlens
```

**GitHub in VS Code**

```powershell
code --install-extension github.vscode-pull-request-github
code --install-extension github.vscode-github-actions
code --install-extension eamodio.gitlens
```

**Extras** (GitHub CLI, ccache, Doxygen, Google Benchmark)

```powershell
winget install --id GitHub.cli -e --accept-package-agreements --accept-source-agreements
& "C:\msys64\usr\bin\bash.exe" -lc "pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-ccache mingw-w64-ucrt-x86_64-doxygen mingw-w64-ucrt-x86_64-benchmark"
code --install-extension cschlosser.doxdocgen
code --install-extension ms-vscode.hexeditor
```

## 4. Configure Git and GitHub

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global core.autocrlf true
gh auth login
gh auth setup-git
```

Use the same email as your GitHub account. For `gh auth login`, choose GitHub.com, HTTPS, then "Login with a web browser".

## 5. Want the apps after all?

Python is not required: just start `setup.bat`. If no Python is installed, it downloads a private copy into the kit's `.runtime` folder, without installing anything on the system.
