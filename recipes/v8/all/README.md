# V8 Conan Package
V8 is Google's open source JavaScript engine.

> This packages includes a support fix for *M1 MacOS* computers.

## Installation

```shell script
git clone https://github.com/luizgabriel/conan-v8 && cd conan-v8
conan export . google/stable
```

In your conanfile.txt, add:
```
[requires]
v8/10.1.69@google/stable
```
