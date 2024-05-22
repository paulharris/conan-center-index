# TODO: each time this recipe is executed, /home/user/.cache/.python-venv adds another folder ~280MB and will consume the disk...

# TODO: increase memory access: https://groups.google.com/g/v8-dev/c/-k10-Qmy1f8/m/1kEWMNMFAgAJ

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.env import Environment
from conan.tools.files import apply_conandata_patches, export_conandata_patches, chdir, mkdir, replace_in_file, copy
from conan.tools.microsoft import check_min_vs, is_msvc_static_runtime, is_msvc, msvc_runtime_flag
from conan.tools.scm import Version, Git

# for source-from-tarball
from conan.tools.files import unzip

import os
import re
import shutil

# To update the version, check https://chromiumdash.appspot.com/branches
# Choose the appropriate branch (eg the "extended stable" branch),
# then scroll down to find that branch, and the V8 column.
# It will be labeled with the git branch name.  Click it.
# Look at the commit log shown and choose the most recent version number.
#
# TODO try downloading tarball from: https://gsdview.appspot.com/chromium-browser-official/?marker=chromium-122.0.6200.0-testdata.tar.x%40
#
# TODO or get tarball/zips from the github mirror: https://github.com/chromium/chromium

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
            # NOT NEEDED ... "v8_enable_pointer_compression":        ["default", True, False],
            # NOT NEEDED ... "v8_enable_pointer_compression_8gb":    ["default", True, False],

            "is_debug":          [False, True],     # because, we often want release versions in a debug context
            "dcheck_always_on":  [False, True],
            "symbol_level":      ["default", 0, 1, 2],

            "v8_enable_sandbox": [False, True], # if true, allows engine to work with memory allocated outside the sandbox

            "v8_enable_webassembly": [False, True],


# TODO try #            # use external ICU, or v8's bundled ICU
# TODO try #            # with no ICU, i18n support will be disabled
# TODO try #            "use_icu":  ["none", "bundled", "system"],
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

            # NOT NEEDED ... "v8_enable_pointer_compression":        "default",
            # NOT NEEDED ... "v8_enable_pointer_compression_8gb":    "default",

            "is_debug":          False,     # because, we often want release versions in a debug context
            "dcheck_always_on":  False,
            "symbol_level":      "default",

            "v8_enable_sandbox": False,

            "v8_enable_webassembly": False,

# TODO try #            # use system (conan) supplied ICU by default
# TODO try #            "use_icu":  "system",
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
            if str(self.settings.compiler) == "msvc":
                if str(self.settings.compiler.version) not in ["191", "192", "193"]:
                    raise ConanInvalidConfiguration("Only msvc 191,192,193 is supported (VC 2017,2019,2022 -> 15,16,17 -> 191,192,193).")
                return True
            # elif ...
            #   Add more compilers here, but if we aren't building with the Windows SDK then return false
            elif str(self.settings.compiler) == "clang":
                if str(self.settings.compiler.version) not in ["18"]:
                    raise ConanInvalidConfiguration("Only clang 18 supported, had some trouble with clang-17")
                return True
            else:
                raise ConanInvalidConfiguration("Only 'msvc' and 'clang' compilers currently known to be supported - update recipe.")
        else:
            return False

    def configure(self):
        self._uses_msvc_runtime()   # will raise Exception if invalid
        if self.settings.compiler == "gcc" and self.settings.compiler.version != "9":
            raise ConanInvalidConfiguration("V8 doesn't appear to compile with newer GCCs, due to stricter language rules (related to constexpr use-before-definition). As of V8 12.1.x and 12.3.x, the chromium buildbots are still on GCC-9, so the errors aren't apparent to the project developers.  There do seem to be some patches in the pipeline for GCC-12+, so perhaps it will be fixed in the future.")

    def system_requirements(self):
        # TODO this isn't allowed ...
        # if self.info.settings.os == "Linux":
            # if not shutil.which("lsb-release"):
                # tools.not-allowed-S-ystemPackageTool().install("lsb-release")
        self._check_python_version()

    def build_requirements(self):
        if not shutil.which("ninja"):
            self.tool_requires("ninja/[>=1]")
        if self.settings.os != "Windows":
            if not shutil.which("bison"):
                self.tool_requires("bison/[>=3.8.2]")
            if not shutil.which("gperf"):
                self.tool_requires("gperf/[>=3.1]")
            if not shutil.which("flex"):
                self.tool_requires("flex/[>=2.6.4]")

    def _make_environment(self):
        """set the environment variables, such that the google tooling is found (including the bundled python2)"""
        env = Environment()
        env.prepend_path("PATH", os.path.join(self.source_folder, "depot_tools"))
        env.define("DEPOT_TOOLS_PATH", os.path.join(self.source_folder, "depot_tools"))
        if self.info.settings.os == "Windows":
            env.define("DEPOT_TOOLS_WIN_TOOLCHAIN", "0")
            # keep this in sync with _uses_msvc_runtime()
            if str(self.info.settings.compiler) == "msvc":
                if str(self.info.settings.compiler.version) == "191": # "15":
                    env.define("GYP_MSVS_VERSION", "2017")
                elif str(self.info.settings.compiler.version) == "192": # "16":
                    env.define("GYP_MSVS_VERSION", "2019")
                elif str(self.info.settings.compiler.version) == "193": # "17":
                    env.define("GYP_MSVS_VERSION", "2022")
                else:
                    raise ConanInvalidConfiguration("Only msvc 191,192,193 is supported (VC 2017,2019,2022 -> 15,16,17 -> 191,192,193).")
            elif str(self.settings.compiler) == "clang":
                if str(self.settings.compiler.version) == "18":
                    # this makes no sense... should be done different
                    env.define("GYP_MSVS_VERSION", "2022")
                else:
                    raise ConanInvalidConfiguration("Clang confusion todo")
            else:
                raise ConanInvalidConfiguration("Only 'msvc' and 'clang' compilers currently known to be supported - update recipe.")

        if self.info.settings.os == "Macos" and self.gn_arch == "arm64":
            env.define("VPYTHON_BYPASS", "manually managed python not supported by chrome operations")
        return env

    def source(self):
        # we get the source in build(), as it depends on the operating system
        pass

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

        # Kept for future reference... in case we need to adjust the Windows SDK used
        # if Version(self.version) == "11.0.226.19":
        #     # Assume the most recent Windows SDK is installed,
        #     # otherwise v8 will assume the old SDK from msvc2019 era
        #     # v8 wants to only use SDKs that it has tested, but I want to use a newer SDK with 2022
        #     win_setup_toolchain_file = os.path.join(v8_source_root, "build", "toolchain", "win", "setup_toolchain.py")
        #     replace_in_file(self, win_setup_toolchain_file,
        #         "10.0.20348.0",
        #         "10.0.22621.0"
        #     )

    def _define_conan_toolchain(self):
        v8_source_root = os.path.join(self.source_folder, "v8")
        conan_toolchain_folder = os.path.join(v8_source_root, "build", "toolchain", "conan", "linux")
        self._patch_gn_build_system("v8_linux_toolchain.gn", conan_toolchain_folder)

        # get compilers and set them up
        compilers_from_conf = self.conf.get("tools.build:compiler_executables", default={}, check_type=dict)
        cc = compilers_from_conf.get("c", "UNKNOWN")
        cxx = compilers_from_conf.get("cpp", "UNKNOWN")

        replace_in_file(self, os.path.join(conan_toolchain_folder, "BUILD.gn"),
                "conan_compiler_cc",
                cc
                )

        replace_in_file(self, os.path.join(conan_toolchain_folder, "BUILD.gn"),
                "conan_compiler_cxx",
                cxx
                )

        # v8 12.1.x wanted to add this warning in the compiler flags,
        # but clang-17 didn't support it. .. TODO how to do version-lower-than
        if "clang" in str(self.info.settings.compiler).lower():
            # needs to be a second if to avoid early-evaluation (gives an error about how 17 is not valid for msvc)
            if self.settings.compiler.version == "17":
                compiler_build_gn = os.path.join(v8_source_root, "build", "config", "compiler", "BUILD.gn")
                replace_in_file( self, compiler_build_gn, "-Wno-thread-safety-reference-return", "")


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
            # Disable PGO, it requires (large) profiles to be downloaded,
            # need to add "checkout_pgo_profiles": True to 'custom_vars' in .gclient config,
            # and then run "gclient runhooks", but it didn't work for me (nothing downloaded).
            # Expecting to find (eg) v8/tools/builtins-pgo/profiles/x86.profile 
            "chrome_pgo_phase = 0",

            #
            # Disable sanitizers, there is a TODO in v8 to remove this flag for official builds
            # HOWEVER, not sure if removal ==> true or false
            "is_cfi = false",

            # don't ask v8 to use a particular linker
            'use_lld = false',
            'use_gold = false',
            'use_thin_lto = false', # LTO not supported without LLD

            #
            # and, ensure dcheck is off as well
            "dcheck_always_on = {}".format("true" if self.options.dcheck_always_on else "false"),

            "is_debug = %s" % ("true" if want_debug else "false"),

            # TODO iterator debugging is MUCH slower, probably don't want to enable that.
            # "enable_iterator_debugging = " + ("true" if want_debug else "false")

            "target_cpu = \"%s\"" % self.gn_arch,

            "is_chrome_branded = false",
            "treat_warnings_as_errors = false",
            "use_glib = false",
            "use_sysroot = false",  # note: warning in 11.6.189.19 that this has no effect
            "use_custom_libcxx = false",
            "use_custom_libcxx_for_host = false",

            # monolithic creates one library from the multiple components,
            # AND includes the external startup data internally (I think)
            # "v8_monolithic = %s" % ("true" if self.options.v8_monolithic else "false"),
            # ALWAYS do monolithic for static builds, and always do component builds for shared builds
            # TODO Windows wouldn't build component-shared (msvc: errors related to DLL+thread data)
            #  and building monolithic-shared produced a static lib anyway.
            #  So for now, Windows is static-only, while Linux can be shared.
            "v8_monolithic = {}".format("true" if not self.options.shared else "false"),
            "v8_static_library = {}".format("false" if self.options.shared else "true"),

            # Note: Can't enable this on iOS
            # This isn't possible with monolith, will build in shared libs
            "is_component_build = {}".format("true" if self.options.shared else "false"),

            # Keep the number of symbols small
            # TODO: symbol_level = -1 (auto) 0 (no syms) 1 (minimum syms for backtrace) 2 (full syms)
# CRASH TESTING #            "symbol_level = 0",
# CRASH TESTING #            "v8_symbol_level = 0",

            # Generate an external header with all the necessary external V8 defines
            "v8_generate_external_defines_header = true",

            # From archlinux: https://aur.archlinux.org/cgit/aur.git/tree/PKGBUILD?h=v8-r&id=1c1910e4afeeecccfbfc2cc9459d6d0078a11ab8
            # On by default with caged heap, which is enabled by default on x64 ...  "cppgc_enable_young_generation = true",
            # Don't need? "v8_enable_backtrace = true",
            # Don't need? "v8_enable_disassembler = true",
# CRASH TESTING #            "v8_enable_i18n_support = true",    # might be useful
# CRASH TESTING #            "v8_enable_object_print = true",    # might be useful

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
            "v8_enable_sandbox = {}".format("true" if self.options.v8_enable_sandbox else "false"),
# CRASH TESTING #            "cppgc_enable_young_generation = false",
# CRASH TESTING #            "cppgc_enable_caged_heap = false",

            "v8_enable_webassembly = {}".format("true" if self.options.v8_enable_webassembly else "false"),

            # TODO consider concurrent_links = NUM to reduce number of parallel linker executions (they consume a lot of memory)

            # we won't use the GDBJIT interface: https://v8.dev/docs/gdb-jit
            "v8_enable_gdbjit = false",
        ]


        # note: don't use True/False, we need text true/false for later
        is_clang = "true" if ("clang" in str(self.info.settings.compiler).lower()) else "false"
        gen_arguments += ["is_clang = " + is_clang]

        if is_clang == "true":
            gen_arguments += [
                    # Not needed in 12.2 ... 'find_bad_constructs = false',

                    # Disable these, they add more flags that aren't supported by regular compilers
                    # This flag is used when using Chrome-specific compiler plugins, with Chrome's clang.
                    'clang_use_chrome_plugins = false',

                    # Tell v8 where our "clang base path" is, don't leave it set to default
                    f'clang_base_path = "/usr/lib/llvm-{self.settings.compiler.version}"',
                    f'clang_version = {self.settings.compiler.version}',
                ]
            if self.settings.compiler.version == "17":
                gen_arguments += [
                        # Pretend we are doing the "android mainline" which uses clang17 and disables
                        # some of the advanced clang18 stuff that aren't supported in clang17
                        "llvm_android_mainline = true"
                    ]

        if self.options.symbol_level != "default":
            gen_arguments += [f"symbol_level = {self.options.symbol_level}"]

        if self.options.use_rtti != "default":
            gen_arguments += ["use_rtti = %s" % ("true" if self.options.use_rtti else "false")]

# CRASH TESTING #        if self.options.v8_enable_pointer_compression != "default":
# CRASH TESTING #            gen_arguments += ["v8_enable_pointer_compression = %s" % ("true" if self.options.v8_enable_pointer_compression else "false")]

# CRASH TESTING #        if self.options.v8_enable_pointer_compression_8gb != "default":
# CRASH TESTING #            gen_arguments += ["v8_enable_pointer_compression_8gb = %s" % ("true" if self.options.v8_enable_pointer_compression_8gb else "false")]

# TODO try #        if self.options.use_icu == "none":
# TODO try #            gen_arguments += ["v8_enable_i18n_support = false"]
# TODO try #        elif self.options.use_icu == "bundled":
# TODO try #            pass
# TODO try #        elif self.options.use_icu == "system":
# TODO try #            gen_arguments += ["use_system_icu = 1"]

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
        # ?? if self.options.v8_monolithic:
        gen_arguments += [ "v8_use_external_startup_data = false"  ]
        # gen_arguments += [
            # "v8_use_external_startup_data = %s" % ("true" if self.options.use_external_startup_data else "false")
        # ]

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


    def generate(self):
        # Note: This environment is not available in the source() method
        env = self._make_environment()
        envvars = env.vars(self, scope="build")
        envvars.save_script("depot_env")


    def build(self):
        breakpoint()
        max_ram = os.getenv("CONAN_BUILD_MAX_RAM_GB")

        if max_ram is None:
            raise ConanInvalidConfiguration("Specify CONAN_BUILD_MAX_RAM_GB in the environment!")
        max_ram = int(max_ram)
        if max_ram <= 0:
            raise ConanInvalidConfiguration("Specify CONAN_BUILD_MAX_RAM_GB in the environment - must be more than zero")

        max_num_parallel = 0
        num_parallel = build_jobs(self)

        # Instead of doing this, set tools.build:jobs=20
        if self.info.settings.build_type == "Debug":
            # Debug builds can consume a LOT of ram, assume 2GB per job
            max_num_parallel = max_ram/2
        else:
            # Guess release can use 1GB per compiler
            max_num_parallel = max_ram

        if num_parallel > max_num_parallel:
            num_parallel = max_num_parallel


        #### GET THE SOURCE ####
        if True:
        # if False:
            # NOTE: To make a new tar file:
            #   cd ~/.conan2/p/v8WHATEVERHASH/s
            #   tar cf /build/mx/v8-src-VERSION.NUM.tar .
            if self.info.settings.os == "Windows":
                unzip(self, "m:/conan4/v8-src-{}.tar.gz".format(self.version), strip_root=False)
            else:
                unzip(self, "file:///build/mx/v8-src-{}.tar.gz".format(self.version), strip_root=False)
        else:
            # else, do the long and involved git method
            git = Git(self)
            depot_repo = "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
            git.clone(url=depot_repo, target="depot_tools", args=["--depth","1"])

            # Note: switching source based on platform/compiler/etc is not recommended in source() as the configuration can change with the next build.
            # however, the source is HUGE, so lets do this switch.
            if self.info.settings.os == "Macos" and self.gn_arch == "arm64":
                mkdir(self, "v8")
                with chdir(self, "v8"):
                    self.run("echo \"mac-arm64\" > .cipd_client_platform")

            env = self._make_environment()
            with env.vars(self).apply():
                # self.run("gclient")   -- does not appear to be necessary
                self.run("fetch v8")

                with chdir(self, "v8"):
                    self.run("git checkout {}".format(self.version))
                    self.run("gclient sync")
                    self.run("gclient sync -D")  # remove dependency folders that have been removed since last sync

        # we have got the source ...
        apply_conandata_patches(self)

        v8_source_root = os.path.join(self.source_folder, "v8")

        # using the sample-config-generator approach
        if False:
            env = self._make_environment()
            envvars = env.vars(self, scope="build")
            with envvars.apply():
                self.run("python --version")
#                print(generator_call)
#                self.run(generator_call)

                # Method to use the v8gen to create a config based on a sample
                self.run("./tools/dev/v8gen.py x64.release.sample -- v8_generate_external_defines_header=true v8_enable_sandbox=false is_debug=true symbol_level=2 is_component_build=true v8_monolithic=false dcheck_always_on=true")
                self.run(f"ninja -j {num_parallel} -C out.gn/x64.release.sample")
            return

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
                f.write("\n")   # blank line at the end

            mkdir(self, "chrome")
            with chdir(self, "chrome"):
                with open("VERSION", "w") as f:
                    # I don't know the format of this file,
                    # only that v8/build/compute_build_timestamp.py is expecting
                    # the 4th line to start with PATCH= and end with a number,
                    # which it uses to compute an offset from a build date.
                    f.write("Line 1\nLine 2\nLine 3\nPATCH=0\n")

            generator_call = f"gn gen {self.build_folder}"

            if True:
                self.run("python --version")
                print(generator_call)
                self.run(generator_call)

                # not sure why in version 12, it couldn't find the v8-gn.h header
                # so we will build it and then copy it into place for the rest of the build to find.
                self.run(f"ninja -v -j {num_parallel} -C {self.build_folder} gen_v8_gn")
                copy(self, pattern="*.h",
                    dst=os.path.join(self.build_folder, "v8", "include"),
                    src=os.path.join(self.build_folder, "gen", "include"),
                    keep_path=True)

                if self.options.shared:
                    self.run(f"ninja -j {num_parallel} -C {self.build_folder}")  # not sure what to specify here, so build all
                else:
                    self.run(f"ninja -j {num_parallel} -C {self.build_folder} v8_monolith")


    def package(self):
        # licences
        copy(self, pattern="LICENSE*",
                dst=os.path.join(self.package_folder, "licenses"),
                src=os.path.join(self.build_folder, "v8"))

        # the normal headers
        copy(self, pattern="*.h",
                dst=os.path.join(self.package_folder, "include"),
                src=os.path.join(self.build_folder, "v8", "include"),
                keep_path=True)

        # headers generated during build, including v8-gn.h (already in include dir!)
        # but especially the inspector/*.h headers, for v8-inspector-protocol.h to include
        # eg inspector/Debugger.h
        copy(self, pattern="*.h",
            dst=os.path.join(self.package_folder, "include"),
            # src=os.path.join(self.build_folder, "v8", "out.gn", "x64.release.sample", "gen", "include"),
            src=os.path.join(self.build_folder, "gen", "include"),
            keep_path=True)

        # we also need to keep icudata file
        copy(self, pattern="icudtl.dat",
            dst=os.path.join(self.package_folder, "res"),
            # src=os.path.join(self.build_folder, "v8", "out.gn", "x64.release.sample"),
            src=self.build_folder)

        # copy the args.gn file, it might be useful to see the v8 args used to build
        copy(self, pattern="args.gn",
            dst=self.package_folder,
            src=self.build_folder)

        # FOR SAMPLE-BASED BUILD ... src=os.path.join(self.build_folder, "v8", "out.gn", "x64.release.sample", "obj"),

        if self.settings.os == "Windows":
            if self.options.shared:
                print("TODO figure out what files to copy for this situation")
                breakpoint()
            else:
                # windows static library
                copy(self, pattern="*v8_monolith.lib",
                        dst=os.path.join(self.package_folder, "lib"),
                        src=os.path.join(self.build_folder),
                        keep_path=False)
        else:
            if self.options.shared:
                copy(self, pattern="lib*.so",
                        dst=os.path.join(self.package_folder, "lib"),
                        src=self.build_folder,
                        keep_path=False)
            else:
                # linux static library (libv8_monolith.a)
                copy(self, pattern="libv8_monolith.a",
                        dst=os.path.join(self.package_folder, "lib"),
                        src=os.path.join(self.build_folder, "obj"),
                        keep_path=False)


    def package_info(self):
        if self.options.shared:
            self.cpp_info.libs = ["v8", "v8_libplatform"]
        else:
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
            self.cpp_info.system_libs.extend(["pthread","dl","atomic"])
