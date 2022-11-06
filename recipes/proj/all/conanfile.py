from conan import ConanFile
from conan.tools.apple import is_apple_os
from conan.tools.cmake import CMake, CMakeDeps, CMakeToolchain, cmake_layout
from conan.tools.env import VirtualBuildEnv
from conan.tools.files import apply_conandata_patches, export_conandata_patches, get, copy, rmdir, replace_in_file, collect_libs, rm
from conan.tools.microsoft import is_msvc
from conan.tools.scm import Version
import os

from conans import tools as tools_legacy


required_conan_version = ">=1.53.0"


class ProjConan(ConanFile):
    name = "proj"
    description = "Cartographic Projections and Coordinate Transformations Library."
    license = "MIT"
    topics = "dsp", "proj", "proj4", "projections", "gis", "geospatial"
    homepage = "https://proj.org"
    url = "https://github.com/conan-io/conan-center-index"

    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "threadsafe": [True, False],
        "with_tiff": [True, False],
        "with_curl": [True, False],
        "build_executables": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
        "threadsafe": True,
        "with_tiff": True,
        "with_curl": True,
        "build_executables": True,
    }

    @property
    def _settings_build(self):
        return getattr(self, "settings_build", self.settings)

    def export_sources(self):
        self.copy("CMakeLists.txt")
        export_conandata_patches(self)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC
        if Version(self.version) < "7.0.0":
            del self.options.with_tiff
            del self.options.with_curl

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

    def layout(self):
        cmake_layout(self, src_folder="src")

    def requirements(self):
        self.requires("nlohmann_json/3.11.2")
        self.requires("sqlite3/3.39.4")
        if self.options.get_safe("with_tiff"):
            self.requires("libtiff/4.4.0")
        if self.options.get_safe("with_curl"):
            self.requires("libcurl/7.85.0")

    def build_requirements(self):
        if hasattr(self, "settings_build"):
            self.tool_requires("sqlite3/3.39.4")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], destination=self.source_folder, strip_root=True)

    def build(self):
        self._patch_sources()
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def _patch_sources(self):
        apply_conandata_patches(self)

        cmakelists = os.path.join(self.source_folder, "CMakeLists.txt")
        replace_in_file(self, cmakelists, "/W4", "")

        # Fix up usage of SQLite3 finder outputs
        rm(self, "FindSqlite3.cmake", os.path.join(self.source_folder, "cmake"))
        replace_in_file(self, cmakelists, "SQLITE3_FOUND", "SQLite3_FOUND")
        replace_in_file(self, cmakelists, "SQLITE3_VERSION", "SQLite3_VERSION")
        replace_in_file(self, cmakelists, "find_package(Sqlite3 REQUIRED)", "find_package(SQLite3 REQUIRED MODULE)")

        # Let CMake install shared lib with a clean rpath !
        if Version(self.version) >= "7.1.0" and Version(self.version) < "9.0.0":
            replace_in_file(self, cmakelists,
                                  "set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)",
                                  "")

        # Aggressive workaround against SIP on macOS, to handle sqlite3 executable
        # linked to shared sqlite3 lib
        if is_apple_os(self):
            # TODO: no hope for 2 profiles, wait for stable self.dependencies
            #       because we want absolute lib paths of build profile actually
            if not hasattr(self, "settings_build"):
                if Version(self.version) < "8.1.0":
                    cmake_sqlite_call = "CMakeLists.txt"
                    pattern = "${EXE_SQLITE3}"
                else:
                    cmake_sqlite_call = "generate_proj_db.cmake"
                    pattern = "\"${EXE_SQLITE3}\""
                lib_paths = self.dependencies["sqlite3"].cpp_info.libdirs
                replace_in_file(self,
                    os.path.join(self.source_folder, "data", cmake_sqlite_call),
                    "COMMAND {}".format(pattern),
                    "COMMAND ${{CMAKE_COMMAND}} -E env \"DYLD_LIBRARY_PATH={}\" {}".format(
                        ":".join(lib_paths), pattern
                    ),
                )

        # unvendor nlohmann_json
        if Version(self.version) < "8.1.0":
            rmdir(self, os.path.join(self.source_folder, "include", "proj", "internal", "nlohmann"))


    def generate(self):
        tc = CMakeToolchain(self)
        tc.variables["USE_THREAD"] = self.options.threadsafe
        tc.variables["BUILD_CCT"] = self.options.build_executables
        tc.variables["BUILD_CS2CS"] = self.options.build_executables
        tc.variables["BUILD_GEOD"] = self.options.build_executables
        tc.variables["BUILD_GIE"] = self.options.build_executables
        tc.variables["BUILD_PROJ"] = self.options.build_executables
        tc.variables["BUILD_PROJINFO"] = self.options.build_executables
        tc.variables["PROJ_DATA_SUBDIR"] = "res"
        if Version(self.version) < "7.0.0":
            tc.variables["PROJ_TESTS"] = False
            tc.variables["BUILD_LIBPROJ_SHARED"] = self.options.shared
            tc.variables["ENABLE_LTO"] = False
            tc.variables["JNI_SUPPORT"] = False
        else:
            tc.variables["ENABLE_TIFF"] = self.options.with_tiff
            tc.variables["ENABLE_CURL"] = self.options.with_curl
            tc.variables["BUILD_TESTING"] = False
            tc.variables["ENABLE_IPO"] = False
            tc.variables["BUILD_PROJSYNC"] = self.options.build_executables and self.options.with_curl
        if Version(self.version) >= "8.1.0":
            tc.variables["NLOHMANN_JSON_ORIGIN"] = "external"
        tc.variables["CMAKE_MACOSX_BUNDLE"] = False

        # Honor BUILD_SHARED_LIBS from conan_toolchain (see https://github.com/conan-io/conan/issues/11840)
        tc.cache_variables["CMAKE_POLICY_DEFAULT_CMP0077"] = "NEW"

        tc.generate()

        tc = CMakeDeps(self)
        tc.generate()

        tc = VirtualBuildEnv(self)
        tc.generate(scope="build")


    def package(self):
        copy(self, "COPYING", dst=os.path.join(self.package_folder, "licenses"), src=self.source_folder)
        cmake = CMake(self)
        cmake.install()
        rmdir(self, os.path.join(self.package_folder, "share"))
        rmdir(self, os.path.join(self.package_folder, "lib", "cmake"))
        rmdir(self, os.path.join(self.package_folder, "lib", "pkgconfig"))


    def package_info(self):
        proj_version = Version(self.version)
        cmake_config_filename = "proj" if proj_version >= "7.0.0" else "proj4"
        cmake_namespace = "PROJ" if proj_version >= "7.0.0" else "PROJ4"
        self.cpp_info.set_property("cmake_file_name", cmake_config_filename)
        self.cpp_info.set_property("cmake_target_name", "{}::proj".format(cmake_namespace))
        self.cpp_info.set_property("pkg_config_name", "proj")
        self.cpp_info.components["projlib"].set_property("cmake_target_name", "{}::proj".format(cmake_namespace))
        self.cpp_info.components["projlib"].set_property("pkg_config_name", "proj")

        self.cpp_info.filenames["cmake_find_package"] = cmake_config_filename
        self.cpp_info.filenames["cmake_find_package_multi"] = cmake_config_filename

        self.cpp_info.components["projlib"].libs = collect_libs(self)
        if self.settings.os in ["Linux", "FreeBSD"]:
            self.cpp_info.components["projlib"].system_libs.append("m")
            if self.options.threadsafe:
                self.cpp_info.components["projlib"].system_libs.append("pthread")
        elif self.settings.os == "Windows":
            if proj_version >= "7.0.0":
                self.cpp_info.components["projlib"].system_libs.append("shell32")
            if proj_version >= "7.1.0":
                self.cpp_info.components["projlib"].system_libs.append("Ole32")
        if not self.options.shared and tools_legacy.stdcpp_library(self):
            self.cpp_info.components["projlib"].system_libs.append(tools_legacy.stdcpp_library(self))
        self.cpp_info.components["projlib"].requires.extend(["nlohmann_json::nlohmann_json", "sqlite3::sqlite3"])
        if self.options.get_safe("with_tiff"):
            self.cpp_info.components["projlib"].requires.append("libtiff::libtiff")
        if self.options.get_safe("with_curl"):
            self.cpp_info.components["projlib"].requires.append("libcurl::libcurl")
        if Version(self.version) < "8.2.0":
            if self.options.shared and is_msvc(self):
                self.cpp_info.components["projlib"].defines.append("PROJ_MSVC_DLL_IMPORT")
        else:
            if not self.options.shared:
                self.cpp_info.components["projlib"].defines.append("PROJ_DLL=")

        res_path = os.path.join(self.package_folder, "res")
        self.output.info("Prepending to PROJ_LIB environment variable: {}".format(res_path))
        self.runenv_info.prepend_path("PROJ_LIB", res_path)

        # TODO: to remove after conan v2, it allows to not break consumers still relying on virtualenv generator
        self.env_info.PROJ_LIB = res_path

        if self.options.build_executables:
            self.buildenv_info.prepend_path("PROJ_LIB", res_path)
            bin_path = os.path.join(self.package_folder, "bin")
            self.output.info("Appending PATH environment variable: {}".format(bin_path))
            self.env_info.PATH.append(bin_path)

        # TODO: to remove in conan v2 once cmake_find_package_* generators removed
        self.cpp_info.names["cmake_find_package"] = cmake_namespace
        self.cpp_info.names["cmake_find_package_multi"] = cmake_namespace
        self.cpp_info.components["projlib"].names["cmake_find_package"] = "proj"
        self.cpp_info.components["projlib"].names["cmake_find_package_multi"] = "proj"
