from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.env import Environment
from conan.tools.files import apply_conandata_patches, export_conandata_patches, chdir, mkdir, replace_in_file, copy
from conan.tools.microsoft import check_min_vs, is_msvc_static_runtime, is_msvc, msvc_runtime_flag
from conan.tools.scm import Version, Git

import os
import re
import shutil

# To update the version, check https://chromiumdash.appspot.com/branches
# Choose the appropriate branch (eg the "extended stable" branch),
# then scroll down to find that branch, and the V8 column.
# It will be labeled with the git branch name.  Click it.
# Look at the commit log shown and choose the most recent version number.

# Notes for manual calls for playing with things:
#
# To check the arguments possible:
#   cd v8   (the source dir)
#   ../../depot_tools/gn args --list ..
#   or, in conan-cache: ../depot_tools/gn args --list ..
#
# To generate:
#   cd v8   (the source dir)
#   ../../depot_tools/gn gen ..
#   or, in conan-cache: ../depot_tools/gn gen ..
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
            "shared":   [True, False],
            "fPIC":     [True, False],
            "use_rtti": ["default", True, False],
            # not if doing monolithic # "use_external_startup_data": [True, False],

            # Disable pointer compression:  Can address more memory.
            # Note that I was not able to successfully build with the _8gb flag on Linux.
            "v8_enable_pointer_compression":        ["default", True, False],
            "v8_enable_pointer_compression_8gb":    ["default", True, False],
            }
    default_options = {
            "shared":   False,
            "fPIC":     True,

            # Chromium/v8 is built with rtti disabled by default
            # If you don't HAVE to turn this on, don't turn it on.
            # You might hit problems if you inherit from v8::ArrayBuffer::Allocator
            # ie missing type_info
            # but you can set (for gcc) --no-rtti on that one file with that code,
            # and everything should (hopefully) link without further problems.
            "use_rtti": "default",

            # not if doing monolithic # "use_external_startup_data": False,

            "v8_enable_pointer_compression":        "default",
            "v8_enable_pointer_compression_8gb":    "default",
            }

    short_paths = True

    # consider this ...
    # no_copy_source = True

    exports_sources = [
        "v8_msvc.gn",
        "v8_linux_toolchain.gn",
        "v8_libcxx_config.gn"
    ]


    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def export_sources(self):
        export_conandata_patches(self)

    def _check_python_version(self):
        """depot_tools requires python >= 2.7.5 or >= 3.8 for python 3 support."""
        python_exe = shutil.which("python")
        if not python_exe:
            msg = ("Python must be available in PATH "
                    "in order to build v8")
            raise ConanInvalidConfiguration(msg)
        # In any case, check its actual version for compatibility
        from six import StringIO  # Python 2 and 3 compatible
        version_buf = StringIO()
        cmd_v = f"\"{python_exe}\" --version"
        self.run(cmd_v, version_buf)
        version_str = version_buf.getvalue().strip()
        p = re.compile(r'Python (\d+\.\d+\.\d+)')
        verstr = p.match(version_str).group(1)
        if verstr.endswith('+'):
            verstr = verstr[:-1]
        version = Version(verstr)
        # >= 2.7.5 & < 3
        py2_min = "2.7.5"
        py2_max = "3.0.0"
        py3_min = "3.8.0"
        if (version >= py2_min) and (version < py2_max):
            msg = f"Found valid Python 2 required for v8: version={version_str}, path={python_exe}"
            self.output.success(msg)
        elif version >= py3_min:
            msg = f"Found valid Python 3 required for v8: version={version_str}, path={python_exe}"
            self.output.success(msg)
        else:
            msg = f"Found Python in path, but with invalid version {verstr} (v8 requires >= {py2_min} and < {py2_max} or >= {py3_min})"
            raise ConanInvalidConfiguration(msg)

    # keep this in sync with self._make_environment()
    # False if not Windows, True if is Windows, will raise Exception if not supported Windows compiler
    def _uses_msvc_runtime(self):
        if self.settings.os == "Windows":
            if self.settings.compiler == "Visual Studio":
                if str(self.settings.compiler.version) not in ["15", "16", "17"]:
                    raise ConanInvalidConfiguration("Only Visual Studio 15,16,17 is supported.")
                return True
            elif str(self.settings.compiler) == "msvc":
                if str(self.settings.compiler.version) not in ["191", "192", "193"]:
                    raise ConanInvalidConfiguration("Only msvc 191,192,193 is supported (VC 2017,2019,2022 -> 15,16,17 -> 191,192,193).")
                return True
            # elif ...
            #   Add more compilers here, but if we aren't building with the Windows SDK then return false
            else:
                raise ConanInvalidConfiguration("Only 'msvc' and 'Visual Studio' compilers currently known to be supported - update recipe.")
        else:
            return False

    def configure(self):
        self._uses_msvc_runtime()   # will raise Exception if invalid

    def system_requirements(self):
        # TODO this isn't allowed ...
        # if self.info.settings.os == "Linux":
            # if not shutil.which("lsb-release"):
                # tools.not-allowed-S-ystemPackageTool().install("lsb-release")
        self._check_python_version()

    def build_requirements(self):
        if not shutil.which("ninja"):
            self.tool_requires("ninja/1.11.1")
        if self.settings.os != "Windows":
            if not shutil.which("bison"):
                self.tool_requires("bison/3.8.2")
            if not shutil.which("gperf"):
                self.tool_requires("gperf/3.1")
            if not shutil.which("flex"):
                self.tool_requires("flex/2.6.4")

    def _make_environment(self):
        """set the environment variables, such that the google tooling is found (including the bundled python2)"""
        env = Environment()
        env.prepend_path("PATH", os.path.join(self.source_folder, "depot_tools"))
        env.define("DEPOT_TOOLS_PATH", os.path.join(self.source_folder, "depot_tools"))
        if self.info.settings.os == "Windows":
            env.define("DEPOT_TOOLS_WIN_TOOLCHAIN", "0")
            # keep this in sync with _uses_msvc_runtime()
            if str(self.info.settings.compiler) == "Visual Studio":
                if str(self.info.settings.compiler.version) == "15":
                    env.define("GYP_MSVS_VERSION", "2017")
                elif str(self.info.settings.compiler.version) == "16":
                    env.define("GYP_MSVS_VERSION", "2019")
                elif str(self.info.settings.compiler.version) == "17":
                    env.define("GYP_MSVS_VERSION", "2022")
                else:
                    raise ConanInvalidConfiguration("Only Visual Studio 15,16,17 is supported.")
            elif str(self.info.settings.compiler) == "msvc":
                if str(self.info.settings.compiler.version) == "191": # "15":
                    env.define("GYP_MSVS_VERSION", "2017")
                elif str(self.info.settings.compiler.version) == "192": # "16":
                    env.define("GYP_MSVS_VERSION", "2019")
                elif str(self.info.settings.compiler.version) == "193": # "17":
                    env.define("GYP_MSVS_VERSION", "2022")
                else:
                    raise ConanInvalidConfiguration("Only msvc 191,192,193 is supported (VC 2017,2019,2022 -> 15,16,17 -> 191,192,193).")
            else:
                raise ConanInvalidConfiguration("Only 'msvc' and 'Visual Studio' compilers currently known to be supported - update recipe.")

        if self.info.settings.os == "Macos" and self.gn_arch == "arm64":
            env.define("VPYTHON_BYPASS", "manually managed python not supported by chrome operations")
        return env

    def source(self):
        git = Git(self)
        depot_repo = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
        git.clone(url=depot_repo, target="depot_tools", args=["--depth","1"])

        if self.info.settings.os == "Macos" and self.gn_arch == "arm64":
            mkdir(self, "v8")
            with chdir(self, "v8"):
                self.run("echo \"mac-arm64\" > .cipd_client_platform")

        env = self._make_environment()
        envvars = env.vars(self, scope="build")
        with envvars.apply():
            # self.run("gclient")   -- does not appear to be necessary
            self.run("fetch v8")

            with chdir(self, "v8"):
                self.run("git checkout {}".format(self.version))
                self.run("gclient sync")

    @property
    def gn_arch(self):
        arch_map = {
            "x86_64": "x64",
            "armv8": "arm64"
        }

        arch = str(self.info.settings.arch)
        return arch_map.get(arch, arch)

    def _install_system_requirements_linux(self):
        """some extra script must be executed on linux"""
        self.output.info("Calling v8/build/install-build-deps.sh")
        env = Environment()
        env.prepend_path("PATH", os.path.join(self.source_folder, "depot_tools"))
        envvars = env.vars(self, scope="build")
        with envvars.apply():
            sh_script = self.source_folder + "/v8/build/install-build-deps.sh"
            self.run("chmod +x " + sh_script)
            cmd = sh_script + " --unsupported --no-arm --no-nacl --no-backwards-compatible --no-chromeos-fonts --no-prompt "
            cmd = cmd + ("--syms" if str(self.info.settings.build_type) == "Debug" else "--no-syms")
            cmd = "export DEBIAN_FRONTEND=noninteractive && " + cmd
            self.run(cmd)

    def _patch_gn_build_system(self, source_file, dest_folder):
        # Always patch over what is there
        # if os.path.exists(os.path.join(dest_folder, "BUILD.gn")):
            # return True
        mkdir(self, dest_folder)
        shutil.copy(
            os.path.join(self.source_folder, source_file),
            os.path.join(dest_folder, "BUILD.gn"))
        # return False

    def _patch_msvc_runtime(self):
        # Do we still need to do this?
        v8_source_root = os.path.join(self.source_folder, "v8")
        msvc_config_folder = os.path.join(v8_source_root, "build", "config", "conan", "msvc")
        self._patch_gn_build_system("v8_msvc.gn", msvc_config_folder)
        config_gn_file = os.path.join(v8_source_root, "build", "config", "BUILDCONFIG.gn")
        replace_in_file(self, config_gn_file,
            "//build/config/win:default_crt",
            "//build/config/conan/msvc:conan_crt\",\n    \"//build/config/conan/msvc:conan_ignore_warnings"
        )

        if Version(self.version) == "11.0.226.19":
            # Assume the most recent Windows SDK is installed,
            # otherwise v8 will assume the old SDK from msvc2019 era
            # v8 wants to only use SDKs that it has tested, but I want to use a newer SDK with 2022
            win_setup_toolchain_file = os.path.join(v8_source_root, "build", "toolchain", "win", "setup_toolchain.py")
            replace_in_file(self, win_setup_toolchain_file,
                "10.0.20348.0",
                "10.0.22621.0"
            )

        # fix bug in BUILD.gn, was defining a header-target as a lib-target
# ONLY in older v10 version
#        build_gn_file = os.path.join(v8_source_root, "BUILD.gn")
#        replace_in_file(self, build_gn_file,
#            "v8_source_set(\"v8_heap_base_headers\") {",
#            "v8_header_set(\"v8_heap_base_headers\") {"
#        )

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
            replace_in_file(self, config_gn_file,
                "  \"//build/config/conan/libcxx:conan_libcxx\",\n",
                ""
            )
        except:
            pass

        replace_in_file(self, config_gn_file,
            "default_compiler_configs = [",
            "default_compiler_configs = [\n"
            "  \"//build/config/conan/libcxx:conan_libcxx\",\n"
        )

    def _gen_arguments(self):
        # To look for args: grep -r declare_args v8/build/

        # Refer to v8/infra/mb/mb_config.pyl
        # TODO check if we can build Release and link to Debug consumer
        want_debug = str(self.info.settings.build_type) == "Debug"
        is_clang = "true" if ("clang" in str(self.info.settings.compiler).lower()) else "false"

        gen_arguments = [
            # Notes on how other embedders compile:
            # https://groups.google.com/a/chromium.org/g/chromium-dev/c/4F5hM8XMOhQ

            # Note from v8/build/config/BUILDCONFIG.gn version 11.0.226.19 (2023-03-16)
            # IMPORTANT NOTE: (!want_debug) is *not* sufficient to get satisfying
            # performance. In particular, DCHECK()s are still enabled for release builds,
            # which can halve overall performance, and do increase memory usage. Always
            # set "is_official_build" to true for any build intended to ship to end-users.
            #
            "is_official_build = %s" % ("false" if want_debug else "true"),
            #
            # and, ensure dcheck is off as well
            "dcheck_always_on = false",

            "is_debug = %s" % ("true" if want_debug else "false"),

            # TODO iterator debugging is MUCH slower, probably don't want to enable that.
            # "enable_iterator_debugging = " + ("true" if want_debug else "false")

            "target_cpu = \"%s\"" % self.gn_arch,

            # TODO test this, might be faster to link than monolith? for debug cycles
            # Note: Can't enable this on iOS
            # This isn't possible with monolith
            "is_component_build = false",

            "is_chrome_branded = false",
            "treat_warnings_as_errors = false",
            "is_clang = " + is_clang,
            "use_glib = false",
            "use_sysroot = false",
            "use_custom_libcxx = false",
            "use_custom_libcxx_for_host = false",

            # monolithic creates one library from the multiple components,
            # AND includes the external startup data internally (I think)
            "v8_monolithic = true",

            # Keep the number of symbols small
            # TODO: symbol_level = -1 (auto) 0 (no syms) 1 (minimum syms for backtrace) 2 (full syms)
            "symbol_level = 0",
            "v8_symbol_level = 0",

            # Generate an external header with all the necessary external V8 defines
            "v8_generate_external_defines_header = true",

            # From archlinux: https://aur.archlinux.org/cgit/aur.git/tree/PKGBUILD?h=v8-r&id=1c1910e4afeeecccfbfc2cc9459d6d0078a11ab8
            # On by default with caged heap, which is enabled by default on x64 ...  "cppgc_enable_young_generation = true",
            # Don't need? "v8_enable_backtrace = true",
            # Don't need? "v8_enable_disassembler = true",
            "v8_enable_i18n_support = true",    # might be useful
            "v8_enable_object_print = true",    # might be useful

            # Don't need? Debugging? "v8_enable_verify_heap = true",

            # Sandbox is not really useful outside of chrome:
            #
            # https://groups.google.com/g/v8-reviews/c/WTrM_i2xOco
            # commit a7329344e52a0af3461aacaa8c538ddf8992e0d6
            # Author: Samuel Groß <sa...@chromium.org>
            # Date: Tue Jul 19 11:22:14 2022
            #
            # [sandbox] Disable the sandbox by default outside of Chromium builds
            #
            # To work properly and securely, the sandbox requires cooperation from the
            # Embedder, for example in the form of a custom ArrayBufferAllocator and
            # later on custom type tags for external objects. As such, it likely does
            # not make sense to enable the sandbox by default everywhere.
            #
            # Specifically, with sandbox enabled, embedders cannot alloc memory and then
            # wrap it in an ArrayBuffer.  Instead, you would have to copy the memory into
            # a v8-alloced buffer, or, use v8's allocator to allocate memory that would
            # eventually be passed to v8.
            # https://www.electronjs.org/blog/v8-memory-cage
            #
            # TODO: We might need to also disable cppgc_enable_caged_heap and young-generation and pointer-compression?
            "v8_enable_sandbox = false",

            # don't let compiler warnings stop us
            "treat_warnings_as_errors = false",

            # TODO consider concurrent_links = NUM to reduce number of parallel linker executions (they consume a lot of memory)
        ]

        if self.options.use_rtti != "default":
            gen_arguments += ["use_rtti = %s" % ("true" if self.options.use_rtti else "false")]

        if self.options.v8_enable_pointer_compression != "default":
            gen_arguments += ["v8_enable_pointer_compression = %s" % ("true" if self.options.v8_enable_pointer_compression else "false")]

        if self.options.v8_enable_pointer_compression_8gb != "default":
            gen_arguments += ["v8_enable_pointer_compression_8gb = %s" % ("true" if self.options.v8_enable_pointer_compression_8gb else "false")]

        if self.info.settings.os == "Windows":
            gen_arguments += [
                "target_os = \"win\"",
                "conan_compiler_runtime = \"%s\"" % str(msvc_runtime_flag(self)),

                # from v8/build/config/win/BUILD.gn v 11.0.226.19 (2023-03-16)
                # options: app, phone, system, server, desktop
                # "target_winuwp_family = \"desktop\"",
                # SHOULD NOT BE REQUIRED, we are building for win, not winuwp (store apps)

                # TODO do we need to set visual_studio_path / _version ... v8/build/win/visual_studio_version.gni
            ]

        # Not possible if doing monolithic
        # This must be specified.
        gen_arguments += [ "v8_use_external_startup_data = false"  ]
        # gen_arguments += [
            # "v8_use_external_startup_data = %s" % ("true" if self.options.use_external_startup_data else "false")
        # ]

        gen_arguments += [
            "v8_static_library = %s" % ("false" if self.options.shared else "true")
        ]

        if self.info.settings.os == "Linux":
            toolchain_to_use = "//build/toolchain/conan/linux:%s_%s" % (self.info.settings.compiler, self.info.settings.arch)
            gen_arguments += [
                "custom_toolchain=\"%s\"" % toolchain_to_use,
                "host_toolchain=\"%s\"" % toolchain_to_use
            ]

        if self.info.settings.os == "Linux" or self.info.settings.os == "Macos":
            gen_arguments += [
                "conan_compiler_name = \"%s\"" % self.info.settings.compiler,
                "conan_compiler_libcxx = \"%s\"" % self.info.settings.compiler.libcxx
            ]

        return gen_arguments


    def build(self):
        apply_conandata_patches(self)

        v8_source_root = os.path.join(self.source_folder, "v8")

        if self.info.settings.os == "Linux":
            # TODO reenable after testing...
            # self._install_system_requirements_linux()
            self._define_conan_toolchain()

        if self.info.settings.os == "Linux" or self.info.settings.os == "Macos":
            self._path_compiler_config()

        with chdir(self, v8_source_root):
            if is_msvc(self):
                if not is_msvc_static_runtime(self):
                    self._patch_msvc_runtime()

            args = self._gen_arguments()
            args_gn_file = os.path.join(self.build_folder, "args.gn")
            with open(args_gn_file, "w") as f:
                f.write("\n".join(args))

            mkdir(self, "chrome")
            with chdir(self, "chrome"):
                with open("VERSION", "w") as f:
                    # I don't know the format of this file,
                    # only that v8/build/compute_build_timestamp.py is expecting
                    # the 4th line to start with PATCH= and end with a number,
                    # which it uses to compute an offset from a build date.
                    f.write("Line 1\nLine 2\nLine 3\nPATCH=0\n")

            generator_call = f"gn gen {self.build_folder}"

            env = self._make_environment()
            envvars = env.vars(self, scope="build")
            with envvars.apply():
                self.run("python --version")
                print(generator_call)
                self.run(generator_call)
                num_parallel = build_jobs(self)
                self.run(f"ninja -v -j {num_parallel} -C {self.build_folder} v8_monolith")


    def package(self):
        # licences
        copy(self, pattern="LICENSE*",
                dst=os.path.join(self.package_folder, "licenses"),
                src=os.path.join(self.build_folder, "v8"))

        # linux static library
        copy(self, pattern="*v8_monolith.a",
                dst=os.path.join(self.package_folder, "lib"),
                src=os.path.join(self.build_folder, "obj"),
                keep_path=False)

        # windows static library
        copy(self, pattern="*v8_monolith.lib",
                dst=os.path.join(self.package_folder, "lib"),
                src=os.path.join(self.build_folder),    # TODO narrow the src to a subfolder
                keep_path=False)

        # the normal headers
        copy(self, pattern="*.h",
                dst=os.path.join(self.package_folder, "include"),
                src=os.path.join(self.build_folder, "v8", "include"),
                keep_path=True)

        # headers generated during build
        copy(self, pattern="*.h",
            dst=os.path.join(self.package_folder, "include"),
            src=os.path.join(self.build_folder, "gen", "include"),
            keep_path=True)


    def package_info(self):
        self.cpp_info.libs = ["v8_monolith"]

        # Embedders must include v8-gn.h,
        # which will automatically happen if V8_GN_HEADER is defined
        self.cpp_info.defines.append("V8_GN_HEADER=1")

        # No, the consumer should be able to choose what C++ std it builds itself with.
        # The library (v8) should validate that the stdcxx is high enough, only.
        #
        # if self.settings.compiler in ["gcc", "clang", "apple-clang"]:
            # self.cpp_info.cxxflags.append("-std=c++14")

        if self.settings.os == "Windows":
            self.cpp_info.system_libs.extend(["winmm.lib", "dbghelp.lib"])
            # TODO is this necessary? should not have any STL interfaces exposed?
            # self.cpp_info.defines += [ "_HAS_ITERATOR_DEBUGGING=0" ]
        elif self.settings.os == "Linux":
            self.cpp_info.cxxflags.append("-pthread")
            self.cpp_info.system_libs.extend(["pthread","dl"])
