# Install on Linux without the app

Every step the setup app does, as commands. Open a terminal and use the section for your distribution:

| Distribution | Package manager |
|---|---|
| Ubuntu, Debian, Linux Mint, Pop!_OS | apt |
| Fedora | dnf |
| Arch, Manjaro, EndeavourOS | pacman |

Not sure? Run `cat /etc/os-release`.

## 1. Classic pack

### GCC, GDB, CMake, Ninja, Make, Git

```bash
# apt
sudo apt update && sudo apt install -y build-essential gdb cmake ninja-build make git

# dnf
sudo dnf install -y gcc gcc-c++ gdb cmake ninja-build make git

# pacman
sudo pacman -Sy --needed gcc gdb cmake ninja make git
```

### VS Code (from Microsoft's repository)

```bash
# apt
sudo apt install -y wget gpg
wget -qO- https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor --yes -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" | sudo tee /etc/apt/sources.list.d/vscode.list
sudo apt update && sudo apt install -y code

# dnf
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
printf '[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\n' | sudo tee /etc/yum.repos.d/vscode.repo
sudo dnf install -y code
```

On Arch, install `visual-studio-code-bin` from the AUR, or download it from https://code.visualstudio.com/download. The `code` package in the official Arch repositories is the open-source build, which cannot install Microsoft's C/C++ extension.

### VS Code extensions

```bash
code --install-extension ms-vscode.cpptools
code --install-extension ms-vscode.cmake-tools
```

## 2. Check it works

```bash
gcc --version
cat > hello.cpp <<'EOF'
#include <iostream>
int main() { std::cout << "Hello from C++!\n"; }
EOF
g++ -std=c++20 -Wall hello.cpp -o hello
./hello
```

You should see `Hello from C++!`. Nothing to add to PATH: packages are installed in `/usr/bin`.

## 3. Optional packs

**Code quality** (clang-format, clang-tidy, clangd, Cppcheck, Catch2, GoogleTest)

```bash
# apt
sudo apt install -y clang-format clang-tidy clangd cppcheck catch2 libgtest-dev
# dnf
sudo dnf install -y clang-tools-extra cppcheck catch2-devel gtest-devel
# pacman
sudo pacman -S --needed clang cppcheck catch2 gtest

code --install-extension llvm-vs-code-extensions.vscode-clangd
code --install-extension usernamehw.errorlens
```

**GitHub in VS Code**

```bash
code --install-extension github.vscode-pull-request-github
code --install-extension github.vscode-github-actions
code --install-extension eamodio.gitlens
```

**Extras** (GitHub CLI, ccache, Doxygen, Google Benchmark)

```bash
# apt
sudo apt install -y gh ccache doxygen libbenchmark-dev
# dnf
sudo dnf install -y gh ccache doxygen google-benchmark-devel
# pacman
sudo pacman -S --needed github-cli ccache doxygen benchmark

code --install-extension cschlosser.doxdocgen
code --install-extension ms-vscode.hexeditor
```

On older Ubuntu or Debian releases without a `gh` package, follow https://github.com/cli/cli/blob/trunk/docs/install_linux.md

## 4. Configure Git and GitHub

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global core.autocrlf input
gh auth login
gh auth setup-git
```

## 5. Want the apps after all?

Python is not required: just start `./setup.sh`. If no Python is installed, it downloads a private copy into the kit's `.runtime` folder, without installing anything on the system.
