# Reviewing policies

The following policies are preferred during the review, but not mandatory:

<!-- toc -->
## Contents

  * [Trailing white-spaces](#trailing-white-spaces)
  * [Quotes](#quotes)
  * [Subfolder Properties](#subfolder-properties)
  * [Order of methods and attributes](#order-of-methods-and-attributes)
  * [License Attribute](#license-attribute)
  * [Applying Patches](#applying-patches)
  * [CMake](#cmake)
    * [Caching Helper](#caching-helper)
    * [Build Folder](#build-folder)
    * [CMake Configure Method](#cmake-configure-method)
  * [Test Package](#test-package)
    * [Minimalistic Source Code](#minimalistic-source-code)
    * [CMake targets](#cmake-targets)
  * [Recommended feature options names](#recommended-feature-options-names)
  * [Supported Versions](#supported-versions)
    * [Removing old versions](#removing-old-versions)
    * [Adding old versions](#adding-old-versions)<!-- endToc -->

## Trailing white-spaces

Avoid trailing white-space characters, if possible

## Quotes

If possible, try to avoid mixing single quotes (`'`) and double quotes (`"`) in python code (`conanfile.py`, `test_package/conanfile.py`). Consistency is preferred.

## Subfolder Properties

When extracting sources or performing out-of-source builds, it is preferable to use a _subfolder_ attribute, `_source_subfolder` and `_build_subfolder` respectively.

For example doing this with property attributes for these variables:

```py
@property
def _source_subfolder(self):
    return "source_subfolder"

@property
def _build_subfolder(self):
    return "build_subfolder"
```

## Order of methods and attributes

Prefer the following order of documented methods in python code (`conanfile.py`, `test_package/conanfile.py`):

- init
- set_name
- set_version
- export
- export_sources
- config_options
- configure
- layout
- requirements
- package_id
- validate
- build_id
- build_requirements
- system_requirements
- source
- generate
- imports
- build
- package
- package_info
- deploy
- test

the order above resembles the execution order of methods on CI. therefore, for instance, `build` is always executed before `package` method, so `build` should appear before the
`package` in `conanfile.py`.

## License Attribute

The mandatory license attribute of each recipe **should** be a [SPDX license](https://spdx.org/licenses/) [short Identifiers](https://spdx.dev/ids/) when applicable.

## Applying Patches

Patches can be applied in a different protected method, the pattern name is `_patch_sources`. When applying patch files, `tools.patch` is the best option.
For simple cases, `tools.replace_in_file` is allowed.

```py
def _patch_sources(self):
    for patch in self.conan_data.get("patches", {}).get(self.version, []):
        tools.patch(**patch)
    # remove bundled xxhash
    tools.remove_files_by_mask(os.path.join(self._source_subfolder, "lib"), "whateer.*")
    tools.replace_in_file(os.path.join(self._cmakelists_subfolder, "CMakeLists.txt"), "...", "")
```

## CMake

When working with CMake based upstream projects it is prefered to follow these principals. They are not applicable to all projects so they can not be enforced.

### Caching Helper

Due to build times and the lenght to configure CMake multiple times, there is a strong motivation to cache the `CMake` build helper from Conan between the `build()` and `package()` methods.

This can be done by adding a `_cmake` attribute to the `ConanFile` class, but consider it as outdated. The current option is using `@functools.lru_cache(1)` decorator.
As example, take a look on [miniz](https://github.com/conan-io/conan-center-index/blob/16780f87ad3db3be81323ddafc668145e4348513/recipes/miniz/all/conanfile.py#L57) recipe.

### Build Folder

Ideally use out-of-source builds by calling `cmake.configure(build_folder=self._build_subfolder)` when ever possible.

### CMake Configure Method

Use a seperate method to handle the common patterns with using CMake based projects. This method is `_configure_cmake` and looks like the follow in the most basic cases:

```py
@functools.lru_cache(1)
def _configure_cmake(self):
    cmake = CMake(self)
    cmake.definitions["BUILD_STATIC"] = not self.options.shared
    cmake.configure(build_folder=self._build_subfolder)
    return cmake
```

## Test Package

### Minimalistic Source Code

The contents of `test_package.c` or `test_package.cpp` should be as minimal as possible, including a few headers at most with simple
instantiation of objects to ensure linkage and dependencies are correct. Any build system can be used to test the package, but
CMake or Meson are usually preferred.

### CMake targets

When using CMake to test a package, the information should be consumed using the **targets provided by `cmake_find_package_multi` generator**. We
enforce this generator to align with the upcoming
[Conan's new `CMakeDeps` generator](https://docs.conan.io/en/latest/reference/conanfile/tools/cmake/cmakedeps.html?highlight=cmakedeps)
and it should help in the migration (and compatibility) with Conan v2.

In ConanCenter we try to mimic the names of the targets and the information provided by CMake's modules and config files that some libraries
provide. If CMake or the library itself don't enforce any target name, the ones provided by Conan should be recommended. The minimal project
in the `test_package` folder should serve as an example of the best way to consume the package, and targets are preferred over raw variables.

This rule applies for the _global_ target and for components ones. The following snippet should serve as example:

**CMakeLists.txt**
```cmake
cmake_minimum_required(VERSION 3.1.2)
project(test_package CXX)

include(${CMAKE_BINARY_DIR}/conanbuildinfo.cmake)
conan_basic_setup(TARGETS)

find_package(package REQUIRED CONFIG)

add_executable(${PROJECT_NAME} test_package.cpp)
target_link_libraries(${PROJECT_NAME} package::package)
```

We encourage contributors to check that not only the _global_ target works properly, but also the ones for the components. It can be
done creating and linking different libraries and/or executables.

## Recommended feature options names

It's often needed to add options to toggle specific library features on/off. Regardless of the default, there is a strong preference for using positive naming for options. In order to avoid the fragmentation, we recommend to use the following naming conventions for such options:

- enable_<feature> / disable_<feature>
- with_<dependency> / without_<dependency>
- use_<feature>

the actual recipe code then may look like:

```py
    options = {"use_tzdb": [True, False]}
    default_options = {"use_tzdb": True}
```

```py
    options = {"enable_locales": [True, False]}
    default_options = {"enable_locales": True}
```

```py
    options = {"with_zlib": [True, False]}
    default_options = {"with_zlib": True}
```

having the same naming conventions for the options may help consumers, e.g. they will be able to specify options with wildcards: `-o *:with_threads=True`, therefore, `with_threads` options will be enabled for all packages in the graph that support it.

## Supported Versions

In this repository we are building a subset of all the versions for a given library. This set of version changes over time as new versions
are released and old ones stop to be used. 

We always welcome latest releases as soon as they are available, and from time to time we remove old versions mainly due to technical reasons: 
the more versions we have, the more resources that are needed in the CI and the more time it takes to build each pull-request (also, the
more chances of failing because of unexpected errors).

### Removing old versions

When removing old versions, please follow these considerations:
 - keep one version for every major release
 - for the latest major release, at least three versions should be available (latest three minor versions)

Logic associated to removed revisions, and entries in `config.yml` and `conandata.yml` files should be removed as well. If anyone needs to
recover them in the future, Git contains the full history and changes can be recovered from it.

Please, note that even if those versions are removed from this repository, **the packages will always be accessible in ConanCenter remote**
associated to the recipe revision used to build them.

### Adding old versions

We usually don't add old versions unless there is a specific request for it. If you need some old version, please
share in the pull-request what is the motivation. Take into account that the version might be removed in future
pull-requests according to the statements above.