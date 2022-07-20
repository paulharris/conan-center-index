import os
import shutil
import re

from conan import ConanFile
# from conans import CMake
from conans import tools
from conan.errors import ConanInvalidConfiguration

# Notes for manual calls for playing with things:
#
# To check the arguments possible:
#   cd v8   (the source dir)
#   ../../depot_tools/gn args --list ..
#
# To generate:
#   cd v8   (the source dir)
#   ../../depot_tools/gn gen ..
#
# Then to build:
#   cd v8   (the source dir)
#   ninja -v -C .. v8_monolith

class V8Conan(ConanFile):
    name = "v8"
    license = "BSD"
    homepage = "https://v8.dev"
    url = "https://github.com/conan-io/conan-center-index"
    description = "V8 is Google's open source JavaScript engine."
    topics = ("javascript", "interpreter", "compiler", "virtual-machine", "javascript-engine")

    settings = "os", "compiler", "build_type", "arch"
    options = {
            "shared": [True, False],
            "fPIC":   [True, False],
            }
    default_options = {
            "shared": False,
            "fPIC":   True,
            }

    # There is no cmake here... 
    # generators = "cmake"

    # should not be included in CCI recipe... not-allowed-r-evision_mode = "hash"

    short_paths = True

    # consider this ...
    # no_copy_source = True

    exports_sources = [
        "v8_msvc_crt.gn",
        "v8_linux_toolchain.gn",
        "v8_libcxx_config.gn"
    ]


    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def _check_python_version(self):
        """depot_tools requires python >= 2.7.5 or >= 3.8 for python 3 support."""
        python_exe = tools.which("python")
        if not python_exe:
            msg = ("Python must be available in PATH "
                    "in order to build v8")
            raise ConanInvalidConfiguration(msg)
        # In any case, check its actual version for compatibility
        from six import StringIO  # Python 2 and 3 compatible
        version_buf = StringIO()
        cmd_v = "\"{}\" --version".format(python_exe)
        self.run(cmd_v, output=version_buf)
        p = re.compile(r'Python (\d+\.\d+\.\d+)')
        verstr = p.match(version_buf.getvalue().strip()).group(1)
        if verstr.endswith('+'):
            verstr = verstr[:-1]
        version = tools.Version(verstr)
        # >= 2.7.5 & < 3
        py2_min = "2.7.5"
        py2_max = "3.0.0"
        py3_min = "3.8.0"
        if (version >= py2_min) and (version < py2_max):
            msg = ("Found valid Python 2 required for v8:"
                    " version={}, path={}".format(version_buf.getvalue().strip(), python_exe))
            self.output.success(msg)
        elif version >= py3_min:
            msg = ("Found valid Python 3 required for v8:"
                    " version={}, path={}".format(version_buf.getvalue().strip(), python_exe))
            self.output.success(msg)
        else:
            msg = ("Found Python in path, but with invalid version {}"
                    " (v8 requires >= {} and < "
                    "{} or >= {})".format(verstr, py2_min, py2_max, py3_min))
            raise ConanInvalidConfiguration(msg)

    def configure(self):
        if self.settings.os == "Windows":
            if (self.settings.compiler == "Visual Studio" and
                    str(self.settings.compiler.version) not in ["15", "16", "17"]):
                raise ConanInvalidConfiguration("Only Visual Studio 15,16,17 is supported.")

    def system_requirements(self):
        # TODO this isn't allowed ...
        # if self.settings.os == "Linux":
            # if not tools.which("lsb-release"):
                # tools.not-allowed-S-ystemPackageTool().install("lsb-release")
        self._check_python_version()

    def build_requirements(self):
        if not tools.which("ninja"):
            self.build_requires("ninja/1.11.0")
        if self.settings.os != "Windows":
            if not tools.which("bison"):
                self.build_requires("bison/3.7.6")
            if not tools.which("gperf"):
                self.build_requires("gperf/3.1")
            if not tools.which("flex"):
                self.build_requires("flex/2.6.4")

    def _set_environment_vars(self):
        """set the environment variables, such that the google tooling is found (including the bundled python2)"""
        os.environ["PATH"] = os.path.join(self.source_folder, "depot_tools") + os.pathsep + os.environ["PATH"]
        os.environ["DEPOT_TOOLS_PATH"] = os.path.join(self.source_folder, "depot_tools")
        if self.settings.os == "Windows":
            os.environ["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
            if str(self.settings.compiler.version) == "15":
                os.environ["GYP_MSVS_VERSION"] = "2017"
            elif str(self.settings.compiler.version) == "16":
                os.environ["GYP_MSVS_VERSION"] = "2019"
            elif str(self.settings.compiler.version) == "17":
                os.environ["GYP_MSVS_VERSION"] = "2022"
            else:
                raise ConanInvalidConfiguration("Only Visual Studio 15,16,17 is supported.")
        if self.settings.os == "Macos" and self.gn_arch == "arm64":
            os.environ["VPYTHON_BYPASS"] = "manually managed python not supported by chrome operations"

    def source(self):
        tools.Git(folder="depot_tools").clone("https://chromium.googlesource.com/chromium/tools/depot_tools.git",
                                              shallow=True)

        if self.settings.os == "Macos" and self.gn_arch == "arm64":
            self.run("mkdir v8")
            with tools.chdir("v8"):
                self.run("echo \"mac-arm64\" > .cipd_client_platform")

        self._set_environment_vars()
        # self.run("gclient")   -- does not appear to be necessary
        self.run("fetch v8")

        with tools.chdir("v8"):
            self.run("git checkout {}".format(self.version))
            self.run("gclient sync")

    @property
    def gn_arch(self):
        arch_map = {
            "x86_64": "x64",
            "armv8": "arm64"
        }

        arch = str(self.settings.arch)
        return arch_map.get(arch, arch)

    def _install_system_requirements_linux(self):
        """some extra script must be executed on linux"""
        self.output.info("Calling v8/build/install-build-deps.sh")
        os.environ["PATH"] += os.pathsep + os.path.join(self.source_folder, "depot_tools")
        sh_script = self.source_folder + "/v8/build/install-build-deps.sh"
        self.run("chmod +x " + sh_script)
        cmd = sh_script + " --unsupported --no-arm --no-nacl --no-backwards-compatible --no-chromeos-fonts --no-prompt "
        cmd = cmd + ("--syms" if str(self.settings.build_type) == "Debug" else "--no-syms")
        cmd = "export DEBIAN_FRONTEND=noninteractive && " + cmd
        self.run(cmd)

    def _patch_gn_build_system(self, source_file, dest_folder):
        # Always patch over what is there
        # if os.path.exists(os.path.join(dest_folder, "BUILD.gn")):
            # return True
        tools.mkdir(dest_folder)
        shutil.copy(
            os.path.join(self.source_folder, source_file),
            os.path.join(dest_folder, "BUILD.gn"))
        # return False

    def _patch_msvc_runtime(self):
        # Do we still need to do this?
        v8_source_root = os.path.join(self.source_folder, "v8")
        msvc_config_folder = os.path.join(v8_source_root, "build", "config", "conan", "msvc")
        self._patch_gn_build_system("v8_msvc_crt.gn", msvc_config_folder)
        config_gn_file = os.path.join(v8_source_root, "build", "config", "BUILDCONFIG.gn")
        tools.replace_in_file(config_gn_file,
            "//build/config/win:default_crt",
            "//build/config/conan/msvc:conan_crt"
        )

        # Assume the most recent Windows SDK is installed,
        # otherwise v8 will assume the old SDK from msvc2019 era
        # v8 wants to only use SDKs that it has tested, but I want to use a newer SDK with 2022
        win_setup_toolchain_file = os.path.join(v8_source_root, "build", "toolchain", "win", "setup_toolchain.py")
        tools.replace_in_file(win_setup_toolchain_file,
            "10.0.20348.0",
            "10.0.22621.0"
        )

        # fix bug in BUILD.gn, was defining a header-target as a lib-target
        build_gn_file = os.path.join(v8_source_root, "BUILD.gn")
        tools.replace_in_file(build_gn_file,
            "v8_source_set(\"v8_heap_base_headers\") {",
            "v8_header_set(\"v8_heap_base_headers\") {"
        )

    def _define_conan_toolchain(self):
        v8_source_root = os.path.join(self.source_folder, "v8")
        conan_toolchain_folder = os.path.join(v8_source_root, "build", "toolchain", "conan", "linux")
        self._patch_gn_build_system("v8_linux_toolchain.gn", conan_toolchain_folder)

    def _path_compiler_config(self):
        v8_source_root = os.path.join(self.source_folder, "v8")
        libcxx_config_folder = os.path.join(v8_source_root, "build", "config", "conan", "libcxx")
        self._patch_gn_build_system("v8_libcxx_config.gn", libcxx_config_folder)
        config_gn_file = os.path.join(v8_source_root, "build", "config", "BUILDCONFIG.gn")

        # TRY to remove if previously patched (by previous conan build)
        try:
            tools.replace_in_file(config_gn_file,
                "  \"//build/config/conan/libcxx:conan_libcxx\",\n",
                ""
            )
        except:
            pass

        tools.replace_in_file(config_gn_file,
            "default_compiler_configs = [",
            "default_compiler_configs = [\n"
            "  \"//build/config/conan/libcxx:conan_libcxx\",\n"
        )

    def _gen_arguments(self):
        # Refer to v8/infra/mb/mb_config.pyl
        # TODO check if we can build Release and link to Debug consumer
        is_debug = "true" if str(self.settings.build_type) == "Debug" else "false"
        is_clang = "true" if ("clang" in str(self.settings.compiler).lower()) else "false"
        gen_arguments = [
            "is_debug = " + is_debug,

            # TODO iterator debugging is MUCH slower, probably don't want to enable that.
            # "enable_iterator_debugging = " + is_debug,

            "target_cpu = \"%s\"" % self.gn_arch,
            "is_component_build = false",
            "is_chrome_branded = false",
            "treat_warnings_as_errors = false",
            "is_clang = " + is_clang,
            "use_glib = false",
            "use_sysroot = false",
            "use_custom_libcxx = false",
            "use_custom_libcxx_for_host = false",

            # V8 specific settings
            "v8_monolithic = true",
            "v8_static_library = true",
            "v8_use_external_startup_data = false",
            # "v8_enable_backtrace = false",
        ]

        if self.settings.os == "Windows":
            gen_arguments += [
                "conan_compiler_runtime = \"%s\"" % str(self.settings.compiler.runtime)
            ]

        if self.settings.os == "Linux":
            toolchain_to_use = "//build/toolchain/conan/linux:%s_%s" % (self.settings.compiler, self.settings.arch)
            gen_arguments += [
                "custom_toolchain=\"%s\"" % toolchain_to_use,
                "host_toolchain=\"%s\"" % toolchain_to_use
            ]

        if self.settings.os == "Linux" or self.settings.os == "Macos":
            gen_arguments += [
                "conan_compiler_name = \"%s\"" % self.settings.compiler,
                "conan_compiler_libcxx = \"%s\"" % self.settings.compiler.libcxx
            ]

        return gen_arguments


    def build(self):
        v8_source_root = os.path.join(self.source_folder, "v8")
        self._set_environment_vars()

        if self.settings.os == "Linux":
            # TODO reenable after testing...
            # self._install_system_requirements_linux()
            self._define_conan_toolchain()

        if self.settings.os == "Linux" or self.settings.os == "Macos":
            self._path_compiler_config()

        with tools.chdir(v8_source_root):
            if self.settings.os == "Windows" and str(self.settings.compiler) == "Visual Studio":
                self._patch_msvc_runtime()

            args = self._gen_arguments()
            args_gn_file = os.path.join(self.build_folder, "args.gn")
            with open(args_gn_file, "w") as f:
                f.write("\n".join(args))

            generator_call = "gn gen {folder}".format(folder=self.build_folder)

            self.run("python --version")
            print(generator_call)
            self.run(generator_call)
            # breakpoint()
            num_parallel = 4 # self.conf_info.get("tools.build:jobs")
            self.run("ninja -v -j {jobs} -C {folder} v8_monolith".format(jobs=num_parallel, folder=self.build_folder))


    def package(self):
        self.copy(pattern="LICENSE*", dst="licenses", src="v8")
        self.copy(pattern="*v8_monolith.a", dst="lib", keep_path=False)
        self.copy(pattern="*v8_monolith.lib", dst="lib", keep_path=False)
        self.copy(pattern="*.h", dst="include/v8/include", src="v8/include", keep_path=True)


    def package_info(self):
        self.cpp_info.libs = ["v8_monolith"]
        self.cpp_info.includedirs.append("include/v8")
        self.cpp_info.includedirs.append("include/v8/include")

        # Pre-configured settings come with conan-v8
        self.cpp_info.defines.append("V8_COMPRESS_POINTERS")

        # No, the consumer should be able to choose what C++ std it builds itself with.
        # The library (v8) should validate that the stdcxx is high enough, only.
        #
        # if self.settings.compiler in ["gcc", "clang", "apple-clang"]:
            # self.cpp_info.cxxflags.append("-std=c++14")

        if self.settings.os == "Windows":
            self.cpp_info.system_libs.append("winmm.lib")
            self.cpp_info.system_libs.append("dbghelp.lib")
            # TODO is this necessary? should not have any STL interfaces exposed?
            # self.cpp_info.defines += [ "_HAS_ITERATOR_DEBUGGING=0" ]
        elif self.settings.os == "Linux":
            self.cpp_info.cxxflags.append("-pthread")
            self.cpp_info.system_libs.append("pthread")
            self.cpp_info.system_libs.append("dl")
