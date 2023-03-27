from contextlib import contextmanager
import functools
from conan.tools.microsoft import is_msvc
from conans import ConanFile, CMake, tools
from conans.errors import ConanInvalidConfiguration
import glob
import os
import textwrap

required_conan_version = ">=1.43.0"

class ITKConan(ConanFile):
    name = "itk"
    topics = ("itk", "scientific", "image", "processing")
    homepage = "http://www.itk.org/"
    url = "https://github.com/conan-io/conan-center-index"
    license = "Apache-2.0"
    description = "Insight Segmentation and Registration Toolkit"

    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "with_cuda": [True, False],
        "with_dcmtk": [True, False],
        "with_elastix": [True, False],
        "with_gdcm": [True, False],
        "with_python_bindings": [None, "ANY"],
        "with_rtk": [True, False],
        "with_scanco": [True, False],
        "with_gpu": [True, False]  # this will enable certain algortihms to use opencl for gpu off loading.
    }
    default_options = {
        "shared": False,
        "fPIC": True,
        "with_cuda": False,
        "with_dcmtk": True,
        "with_elastix": False,
        "with_gdcm": True,
        "with_python_bindings": None,
        "with_rtk": False,
        "with_scanco": False,
        "with_gpu": True
    }

    short_paths = True
    generators = "cmake", "cmake_find_package"
    _cmake = None

    @property
    def _source_subfolder(self):
        return "source_subfolder"

    @property
    def _build_subfolder(self):
        return "build_subfolder"

    @property
    def _source_elastix_subfolder(self):
        return os.path.join("elastix", "elastix_source")

    @property
    def _source_elastix_buildfolder(self):
        return "elastix_build"

    # TODO: Some packages can be added as optional, but they are not in CCI:
    # - mkl
    # - vtk
    # - opencv

    def export_sources(self):
        self.copy("CMakeLists.txt")
        for patch in self.conan_data.get("patches", {}).get(self.version, []):
            self.copy(patch["patch_file"])

        # files for elastix
        self.copy("elastix/CMakeLists.txt")
        self.copy("elastix/patches/0001-elastix.patch")


    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def configure(self):
        if self.options.shared:
            del self.options.fPIC

    @property
    def _build_bindings(self):
        return self.options.with_python_bindings

    def requirements(self):
        if self.options.with_dcmtk:
            self.requires("dcmtk/3.6.6")

        if self.options.with_gdcm:
            self.requires("gdcm/3.0.9")
        if self.options.with_elastix and self.options.with_python_bindings:
            self.requires("libdeflate/1.14")
            
        self.requires("double-conversion/3.2.0")
        self.requires("eigen/3.4.0")
        self.requires("expat/2.4.8")
        self.requires("fftw/3.3.9")
        self.requires("hdf5/1.12.0")
        self.requires("libjpeg/9d")
        self.requires("libpng/1.6.37")
        self.requires("libtiff/4.3.0")
        self.requires("onetbb/2021.7.0")
        self.requires("zlib/1.2.12")

    def build_requirements(self):
        if self.options.with_rtk and self.settings.os == "Windows":
            self.tool_requires("msys2/cci.latest")

    @contextmanager
    def _build_context(self):
        with tools.vcvars(self) if is_msvc(self) else tools.no_op():
            # next lines force cmake package to be in PATH before the one provided by visual studio (vcvars)
            build_env = tools.RunEnvironment(self).vars if is_msvc(self) else {}
            build_env["MAKEFLAGS"] = "j%d" % tools.cpu_count()
            build_env["PKG_CONFIG_PATH"] = [self.generators_folder, self.build_folder]
            if is_msvc(self):
                # this avoids cmake using gcc from strawberryperl
                build_env["CC"] = "cl"
                build_env["CXX"] = "cl"
            with tools.environment_append(build_env):
                yield


    @property
    def _minimum_cpp_standard(self):
        return 11

    @property
    def _minimum_compilers_version(self):
        return {
            "Visual Studio": "14",
            "gcc": "4.8.1",
            "clang": "3.3",
            "apple-clang": "9",
        }

    def validate(self):
        if self.options.shared and not self.options["hdf5"].shared:
            raise ConanInvalidConfiguration("When building a shared itk, hdf5 needs to be shared too (or not linked to by the consumer).\n"
                                            "This is because H5::DataSpace::ALL might get initialized twice, which will cause a H5::DataSpaceIException to be thrown).")

        if self.options.with_elastix:
            version = tools.Version(self.version)
            if version.major != "5" and version.minor != "3":
                raise ConanInvalidConfiguration("Elastix has only been validated for ITK version 5.3")
            if not self.options.with_gdcm:
                raise ConanInvalidConfiguration("When building elastix support, gdcm needs to be enabled")

        if self.settings.compiler.get_safe("cppstd"):
            tools.check_min_cppstd(self, self._minimum_cpp_standard)

        min_version = self._minimum_compilers_version.get(str(self.settings.compiler))
        if not min_version:
            self.output.warn("{} recipe lacks information about the {} compiler support.".format(
                self.name, self.settings.compiler))
        else:
            if tools.Version(self.settings.compiler.version) < min_version:
                raise ConanInvalidConfiguration("{} requires C++{} support. The current compiler {} {} does not support it.".format(
                    self.name, self._minimum_cpp_standard, self.settings.compiler, self.settings.compiler.version))


    def source(self):
        tools.get(**self.conan_data["sources"][self.version],
                  destination=self._source_subfolder, strip_root=True)

    def _patch_sources(self):
        for patch in self.conan_data.get("patches", {}).get(self.version, []):
            tools.patch(**patch)

    def _patch_rtk(self):
        """
        This patch is only needed on windows with shared libraries.
        If it's not built with this patch, linking against RTK does not work.
        """
        if self.options.with_rtk and self.options.shared and self.settings.os == "Windows":
            tools.replace_in_file("source_subfolder/Modules/Remote/RTK/src/CMakeLists.txt",
                                  "itk_module_add_library(RTK ${RTK_SRCS})",
                                  "itk_module_add_library(RTK ${RTK_SRCS})\n"
                                  "target_link_options(RTK INTERFACE /force)\n")

    def _configure_cmake(self):
        if self._cmake:
            return self._cmake

        self._cmake = CMake(self, generator="Ninja")
        self._cmake.definitions["BUILD_EXAMPLES"] = False
        self._cmake.definitions["BUILD_TESTING"] = False
        self._cmake.definitions["BUILD_DOCUMENTATION"] = False
        self._cmake.definitions["ITK_SKIP_PATH_LENGTH_CHECKS"] = True

        self._cmake.definitions["ITK_USE_SYSTEM_LIBRARIES"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_DOUBLECONVERSION"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_EIGEN"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_FFTW"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_HDF5"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_ICU"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_JPEG"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_PNG"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_TIFF"] = True
        self._cmake.definitions["ITK_USE_SYSTEM_ZLIB"] = True

        # FIXME: Missing Kwiml recipe
        self._cmake.definitions["ITK_USE_SYSTEM_KWIML"] = False
        # FIXME: Missing VXL recipe
        self._cmake.definitions["ITK_USE_SYSTEM_VXL"] = False

        if self.options.with_gdcm:
            self._cmake.definitions["ITK_USE_SYSTEM_GDCM"] = True
            self._cmake.definitions["GDCM_USE_SYSTEM_OPENJPEG"] = True

        self._cmake.definitions["ITK_BUILD_DEFAULT_MODULES"] = False
        self._cmake.definitions["Module_ITKDeprecated"] = False
        self._cmake.definitions["Module_ITKMINC"] = False
        self._cmake.definitions["Module_ITKIOMINC"] = False

        self._cmake.definitions["Module_ITKVideoBridgeOpenCV"] = False

        self._cmake.definitions["Module_ITKIOHDF5"] = True
        self._cmake.definitions["Module_ITKIOTransformHDF5"] = False
        self._cmake.definitions["Module_ITKAnisotropicSmoothing"] = True
        self._cmake.definitions["Module_ITKAntiAlias"] = True
        self._cmake.definitions["Module_ITKBiasCorrection"] = True
        self._cmake.definitions["Module_ITKBinaryMathematicalMorphology"] = True
        self._cmake.definitions["Module_ITKBioCell"] = True
        self._cmake.definitions["Module_ITKClassifiers"] = True
        self._cmake.definitions["Module_ITKColormap"] = True
        self._cmake.definitions["Module_ITKConnectedComponents"] = True
        self._cmake.definitions["Module_ITKConvolution"] = True
        self._cmake.definitions["Module_ITKCurvatureFlow"] = True
        self._cmake.definitions["Module_ITKDeconvolution"] = True
        self._cmake.definitions["Module_ITKDeformableMesh"] = True
        self._cmake.definitions["Module_ITKDenoising"] = True
        self._cmake.definitions["Module_ITKDiffusionTensorImage"] = True
        self._cmake.definitions["Module_ITKDisplacementField"] = True
        self._cmake.definitions["Module_ITKDistanceMap"] = True
        self._cmake.definitions["Module_ITKEigen"] = True
        self._cmake.definitions["Module_ITKFEM"] = True
        self._cmake.definitions["Module_ITKFEMRegistration"] = True
        self._cmake.definitions["Module_ITKFFT"] = True
        self._cmake.definitions["Module_ITKFastMarching"] = True
        self._cmake.definitions["Module_ITKGIFTI"] = True
        self._cmake.definitions["Module_ITKIOCSV"] = True
        self._cmake.definitions["Module_ITKIOGE"] = True
        self._cmake.definitions["Module_ITKIOIPL"] = True
        self._cmake.definitions["Module_ITKIOMesh"] = True
        self._cmake.definitions["Module_ITKIOPhilipsREC"] = True
        self._cmake.definitions["Module_ITKIORAW"] = True
        self._cmake.definitions["Module_ITKIOSiemens"] = True
        self._cmake.definitions["Module_ITKIOSpatialObjects"] = True
        self._cmake.definitions["Module_ITKIOTransformBase"] = True
        self._cmake.definitions["Module_ITKIOTransformInsightLegacy"] = True
        self._cmake.definitions["Module_ITKIOTransformMatlab"] = True
        self._cmake.definitions["Module_ITKIOXML"] = True
        self._cmake.definitions["Module_ITKImageCompare"] = True
        self._cmake.definitions["Module_ITKImageCompose"] = True
        self._cmake.definitions["Module_ITKImageFeature"] = True
        self._cmake.definitions["Module_ITKImageFusion"] = True
        self._cmake.definitions["Module_ITKImageGradient"] = True
        self._cmake.definitions["Module_ITKImageGrid"] = True
        self._cmake.definitions["Module_ITKImageIntensity"] = True
        self._cmake.definitions["Module_ITKImageLabel"] = True
        self._cmake.definitions["Module_ITKImageSources"] = True
        self._cmake.definitions["Module_ITKImageStatistics"] = True
        self._cmake.definitions["Module_ITKIntegratedTest"] = True
        self._cmake.definitions["Module_ITKKLMRegionGrowing"] = True
        self._cmake.definitions["Module_ITKLabelMap"] = True
        self._cmake.definitions["Module_ITKLabelVoting"] = True
        self._cmake.definitions["Module_ITKLevelSets"] = True
        self._cmake.definitions["Module_ITKLevelSetsv4"] = True
        self._cmake.definitions["Module_ITKMarkovRandomFieldsClassifiers"] = True
        self._cmake.definitions["Module_ITKMathematicalMorphology"] = True
        self._cmake.definitions["Module_ITKMetricsv4"] = True
        self._cmake.definitions["Module_ITKNarrowBand"] = True
        self._cmake.definitions["Module_ITKNeuralNetworks"] = True
        self._cmake.definitions["Module_ITKOptimizers"] = True
        self._cmake.definitions["Module_ITKOptimizersv4"] = True
        self._cmake.definitions["Module_ITKPDEDeformableRegistration"] = True
        self._cmake.definitions["Module_ITKPath"] = True
        self._cmake.definitions["Module_ITKPolynomials"] = True
        self._cmake.definitions["Module_ITKQuadEdgeMeshFiltering"] = True
        self._cmake.definitions["Module_ITKRegionGrowing"] = True
        self._cmake.definitions["Module_ITKRegistrationCommon"] = True
        self._cmake.definitions["Module_ITKRegistrationMethodsv4"] = True
        self._cmake.definitions["Module_ITKReview"] = True
        self._cmake.definitions["Module_ITKSignedDistanceFunction"] = True
        self._cmake.definitions["Module_ITKSmoothing"] = True
        self._cmake.definitions["Module_ITKSpatialFunction"] = True
        self._cmake.definitions["Module_ITKTBB"] = True
        self._cmake.definitions["Module_ITKThresholding"] = True
        self._cmake.definitions["Module_ITKVideoCore"] = True
        self._cmake.definitions["Module_ITKVideoFiltering"] = True
        self._cmake.definitions["Module_ITKVideoIO"] = False
        self._cmake.definitions["Module_ITKVoronoi"] = True
        self._cmake.definitions["Module_ITKWatersheds"] = True
        self._cmake.definitions["Module_ITKDICOMParser"] = True

        self._cmake.definitions["Module_ITKVTK"] = False
        self._cmake.definitions["Module_ITKVtkGlue"] = False

        # Disabled on Linux (link errors)
        self._cmake.definitions["Module_ITKLevelSetsv4Visualization"] = False

        # Disabled because Vxl vidl is not built anymore
        self._cmake.definitions["Module_ITKVideoBridgeVXL"] = False

        self._cmake.definitions["Module_IOScanco"] = self.options.with_scanco
        if self.options.with_dcmtk:
            self._cmake.definitions["ITK_USE_SYSTEM_DCMTK"] = True
            self._cmake.definitions["Module_ITKDCMTK"] = True
            self._cmake.definitions["Module_ITKIODCMTK"] = True
            self._cmake.definitions["DCMTK_USE_ICU"] = self.options["dcmtk"].charset_conversion == "icu"

        # Add Cuda modules
        self._cmake.definitions["Module_ITKCudaCommon"] = self.options.with_cuda

        # manage the rtk module
        self._cmake.definitions["Module_RTK"] = self.options.with_rtk
        if self.options.with_rtk:
            self._cmake.definitions["RTK_BUILD_APPLICATIONS"] = False
            self._cmake.definitions["RTK_USE_CUDA"] = self.options.with_cuda

        # Manage GPU settings
        self._cmake.definitions["Module_ITKGPUAnisotropicSmoothing"] = self.options.with_gpu
        self._cmake.definitions["Module_ITKGPUImageFilterBase"] = self.options.with_gpu
        self._cmake.definitions["Module_ITKGPUPDEDeformableRegistration"] = self.options.with_gpu
        self._cmake.definitions["Module_ITKGPURegistrationCommon"] = self.options.with_gpu
        self._cmake.definitions["Module_ITKGPUSmoothing"] = self.options.with_gpu
        self._cmake.definitions["Module_ITKGPUThresholding"] = self.options.with_gpu

        # Manage python bindings
        self._cmake.definitions["ITK_WRAP_PYTHON"] = self.options.with_python_bindings is not None
        if self.options.with_python_bindings:
            self._cmake.definitions["PY_SITE_PACKAGES_PATH"] = os.path.join(self.package_folder, "lib", "site-packages")
            if self.settings.build_type == "Debug" and self.settings.os == "Windows":
                # if you apply the python patch here: https://stackoverflow.com/a/40594968
                # then you need this hack to compile the python portion of the code in debug
                python_lib_folder = os.path.realpath(os.path.join(tools.which("python"), "..", "libs")).replace("\\", "/")
                tools.replace_in_file("CMakeLists.txt",
                                      "\n\nadd_subdirectory(source_subfolder)",
                                      '\n\nlink_directories("{}")\n'
                                      "add_subdirectory(source_subfolder)".format(python_lib_folder),
                                      strict=False)  # TODO: Set strict to true / remove when no longer testing


        if self._build_bindings:
            # this is mostly needed by the GPU components to build properly, but realistically, these
            # are important numeric types.
            self._cmake.definitions["ITK_WRAP_unsigned_long_long"] = True
            self._cmake.definitions["ITK_WRAP_unsigned_short"] = True

        self._cmake.configure(build_folder=self._build_subfolder)
        return self._cmake

    # def generators_folder(self):
    #     pass

    @functools.lru_cache(1)
    def _configure_elastix(self, download_source=True):

        # begin configuring cmake
        cmake = CMake(self, generator="Ninja") #TODO REMOVE NINJA GENERATOR
        cmake.definitions["CONAN_SOURCE_DIR"] = os.path.join(self.build_folder, self._source_subfolder).replace("\\", "/")
        cmake.definitions["BUILD_SHARED_LIBS"] = self.options.shared
        cmake.definitions["ITK_BUILD_SHARED"] = self.options.shared
        # cmake.definitions["ITK_SOURCE_DIR"] = os.path.join(self.build_folder, self._build_subfolder)
        cmake.definitions["ITK_DIR"] = os.path.join(self.build_folder, self._build_subfolder, self._source_subfolder).replace("\\","/")
        cmake.definitions["ITK_CMAKE_DIR"] = os.path.join(self.build_folder, self._source_subfolder, "CMake").replace("\\","/")
        #cmake.definitions["ITK_MODULES_DIR"] = os.path.join(self.package_folder, "lib", "cmake", self._itk_subdir, "Modules")
        cmake.definitions["ELASTIX_USE_OPENCL"] = self.options.with_gpu
        cmake.definitions["ELASTIX_USE_EIGEN"] = True
        cmake.definitions["ELASTIX_USE_OPENMP"] = True
        cmake.definitions["ITK_WRAP_PYTHON"] = self.options.with_python_bindings is not None
        cmake.definitions["ITK_MODULES_DIR"] = os.path.join(self.build_folder, self._build_subfolder, self.source_folder, "lib", "cmake", self._itk_subdir, "Modules")
        cmake.definitions["BUILD_TESTING"] = False

        # cmake.definitions["ITK_FOUND"] = True
        version = tools.Version(self.version)
        cmake.definitions["ITK_VERSION_MAJOR"] = version.major
        cmake.definitions["ITK_VERSION_MINOR"] = version.minor
        cmake.definitions["ITK_VERSION"] = "{}.{}".format(version.major, version.minor)
        cmake.definitions["ITK_WRAPPING"] = self._build_bindings
        cmake.definitions["ITK_CMAKE_DIR"] = os.path.join(self.build_folder, self._source_subfolder, "CMake").replace("\\", "")
        cmake.definitions["ITK_MODULES_DIR"] = os.path.join(self.package_folder, "lib", "cmake", self._itk_subdir, "Modules").replace("\\", "")
        cmake.definitions["ITK_USE_SYSTEM_LIBRARIES"] = True
        cmake.definitions["ITK_USE_SYSTEM_DOUBLECONVERSION"] = True
        cmake.definitions["ITK_USE_SYSTEM_EIGEN"] = True
        cmake.definitions["ITK_USE_SYSTEM_FFTW"] = True
        cmake.definitions["ITK_USE_SYSTEM_HDF5"] = True
        cmake.definitions["ITK_USE_SYSTEM_ICU"] = True
        cmake.definitions["ITK_USE_SYSTEM_JPEG"] = True
        cmake.definitions["ITK_USE_SYSTEM_PNG"] = True
        cmake.definitions["ITK_USE_SYSTEM_TIFF"] = True
        cmake.definitions["ITK_USE_SYSTEM_ZLIB"] = True

        if self.options.with_python_bindings:
            cmake.definitions["PY_SITE_PACKAGES_PATH"] = os.path.join(self.package_folder, "lib", "site-packages")

        cmake_module_path = [
            self.build_folder,
            os.path.join(self.build_folder, self._source_subfolder),
            os.path.join(self.build_folder, self._source_subfolder, "CMake"),
            os.path.join(self.build_folder, self._build_subfolder, self._source_subfolder, "lib", "cmake", self._itk_subdir, "Modules"),
            os.path.join(self.package_folder, "lib", "cmake", self._itk_subdir)
        ]

        # if we are compiling with rtk, we need to add the rtk cuda_wrap_module
        if self.options.with_rtk:
            cmake_module_path.append(
                os.path.join(self.build_folder, self._source_subfolder, "Modules", "Remote", "RTK", "cmake"),
            )
        cmake_module_path_from_environment = os.environ.get("CMAKE_MODULE_PATH")
        if cmake_module_path_from_environment:
            cmake_module_path.extend(cmake_module_path_from_environment.split(os.pathsep))

        cmake_module_path = ";".join(cmake_module_path)
        cmake.definitions["CMAKE_PREFIX_PATH"] = cmake_module_path
        cmake.configure(source_folder="elastix", build_folder=self._source_elastix_buildfolder)
        return cmake

    def build(self):
        with self._build_context():
            self._patch_sources()
            cmake = self._configure_cmake()
            self._patch_rtk()
            cmake.build()

            # configure optional itk modules
            if self.options.with_elastix:
                # download the code
                # because Elastix depends on ITK being installed while ITKElastix requires the source folder,
                # we are forced to run cmake.install here
                self._configure_cmake().install()

                # download the elastix source code
                git = tools.Git(folder=self._source_elastix_subfolder)
                git.clone("https://github.com/InsightSoftwareConsortium/ITKElastix", "v0.15.0", shallow=True)

                # configure and patch elastix
                cmake = self._configure_elastix()
                tools.patch(base_path=self._source_elastix_buildfolder,
                            patch_file="elastix/patches/0001-elastix.patch")
                if self.options.with_python_bindings:
                    env = tools.environment_append({"PYTHONPATH": os.path.join(self.source_folder, self._source_subfolder, "Modules", "ThirdParty", "pygccxml", "src")})
                else:
                    env = tools.no_op()
                with env:
                    cmake.build()

    def package(self):
        self.copy("LICENSE", dst="licenses", src=self._source_subfolder)
        if not self.options.with_elastix:
            # install itk
            cmake = self._configure_cmake()
            cmake.install()
        else:
            # only install elastix. itk is already installed during the compilation of elastix
            cmake = self._configure_elastix(download_source=False)
            cmake.install()

        tools.rmdir(os.path.join(self.package_folder, "lib", "pkgconfig"))
        tools.rmdir(os.path.join(self.package_folder, "share"))
        tools.rmdir(os.path.join(self.package_folder, self._cmake_module_dir, "Modules"))
        # Do not remove UseITK.cmake and *.h.in files
        for cmake_file in glob.glob(os.path.join(self.package_folder, self._cmake_module_dir, "*.cmake")):
            if os.path.basename(cmake_file) not in {"UseITK.cmake", "ITKInitializeCXXStandard.cmake"}:
                os.remove(cmake_file)

        self._create_cmake_module_alias_targets(
            os.path.join(self.package_folder, self._module_file_rel_path),
            {target: "ITK::{}".format(target) for target in self._itk_components.keys()},
        )

    @staticmethod
    def _create_cmake_module_alias_targets(module_file, targets):
        content = ""
        for alias, aliased in targets.items():
            content += textwrap.dedent("""\
                if(TARGET {aliased} AND NOT TARGET {alias})
                    add_library({alias} INTERFACE IMPORTED)
                    set_property(TARGET {alias} PROPERTY INTERFACE_LINK_LIBRARIES {aliased})
                endif()
            """.format(alias=alias, aliased=aliased))
        tools.save(module_file, content)

    @property
    def _module_file_rel_path(self):
        return os.path.join(self._cmake_module_dir, "conan-official-{}-targets.cmake".format(self.name))

    @property
    def _cmake_module_dir(self):
        return os.path.join("lib", "cmake", self._itk_subdir)

    @property
    def _itk_subdir(self):
        v = tools.Version(self.version)
        return "ITK-{}.{}".format(v.major, v.minor)

    @property
    def _itk_components(self):
        def libm():
            return ["m"] if self.settings.os in ["Linux", "FreeBSD"] else []

        def optional_modules():
            modules = {}
            if self.options.with_dcmtk:
                modules["ITKIODCMTK"] = {"requires": ["ITKIOImageBase", "dcmtk::dcmtk"]}
            if self.options.with_rtk:
                modules["itkRTK"] = {"libs": ["lpsolve55"],
                                     "includes": [os.path.join("include", "RTK", "lpsolve")],
                                     }
                if self.options.with_cuda:
                    modules["itkRTK"]["libs"].append("ITKCudaCommon")
            if self.options.with_scanco:
                modules["IOScanco"] = {}
            if self.options.with_gdcm:
                modules["ITKIOGDCM"] = {"requires": ["ITKCommon", "ITKIOImageBase", "gdcm::gdcmDICT", "gdcm::gdcmMSFF"]}
            if self.options.with_elastix:
                modules["ITKElastix"] = {"requires": ["libdeflate::libdeflate"]}
            return modules

        modules = optional_modules()
        modules.update({
            "itksys": {},
            "itkvcl": {"system_libs": libm()},
            "itkv3p_netlib": {"system_libs": libm()},
            "itkvnl": {"requires": ["itkvcl"]},
            "itkvnl_algo": {"requires": ["itkv3p_netlib", "itkvnl"]},
            "itktestlib": {"requires": ["itkvcl"]},
            "ITKVNLInstantiation": {
                "requires": [
                    "itkvnl_algo", "itkvnl", "itkv3p_netlib", "itkvcl",
                ],
            },
            "ITKCommon": {
                "requires": [
                    "itksys", "ITKVNLInstantiation", "eigen::eigen",
                    "onetbb::onetbb", "double-conversion::double-conversion",
                ],
                "system_libs": libm(),
            },
            "itkNetlibSlatec": {"requires": ["itkv3p_netlib"]},
            "ITKStatistics": {"requires": ["ITKCommon", "itkNetlibSlatec"]},
            "ITKTransform": {"requires": ["ITKCommon"]},
            "ITKMesh": {"requires": ["ITKTransform"]},
            "ITKMetaIO": {"requires": ["zlib::zlib"]},
            "ITKSpatialObjects": {"requires": ["ITKTransform", "ITKCommon", "ITKMesh"]},
            "ITKPath": {"requires": ["ITKCommon"]},
            "ITKImageIntensity": {},
            "ITKLabelMap": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                ],
            },
            "ITKQuadEdgeMesh": {"requires": ["ITKMesh"]},
            "ITKFastMarching": {},
            "ITKIOImageBase": {"requires": ["ITKCommon"]},
            "ITKSmoothing": {},
            "ITKImageFeature": {"requires": ["ITKSmoothing", "ITKSpatialObjects"]},
            "ITKOptimizers": {"requires": ["ITKStatistics"]},
            "ITKPolynomials": {"requires": ["ITKCommon"]},
            "ITKBiasCorrection": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                ],
            },
            "ITKColormap": {},
            "ITKFFT": {"requires": ["ITKCommon", "fftw::fftw"]},
            "ITKConvolution": {
                "requires": [
                    "ITKFFT", "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                ],
            },
            "ITKDICOMParser": {},
            "ITKDeformableMesh": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform", "ITKImageFeature",
                    "ITKSpatialObjects", "ITKPath", "ITKMesh",
                ],
            },
            "ITKDenoising": {},
            "ITKDiffusionTensorImage": {},
            "ITKIOXML": {"requires": ["ITKIOImageBase", "expat::expat"]},
            "ITKIOSpatialObjects": {"requires": ["ITKSpatialObjects", "ITKIOXML", "ITKMesh"]},
            "ITKFEM": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                    "ITKSmoothing", "ITKImageFeature", "ITKOptimizers", "ITKMetaIO",
                ],
            },
            "ITKPDEDeformableRegistration": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath", "ITKSmoothing",
                    "ITKImageFeature", "ITKOptimizers",
                ],
            },
            "ITKFEMRegistration": {
                "requires": [
                    "ITKFEM", "ITKImageFeature", "ITKCommon", "ITKSpatialObjects",
                    "ITKTransform", "ITKPDEDeformableRegistration",
                ],
            },
            "ITKznz": {"requires": ["zlib::zlib"]},
            "ITKniftiio": {"requires": ["ITKznz"], "system_libs": libm()},
            "ITKgiftiio": {"requires": ["ITKznz", "ITKniftiio", "expat::expat"]},
            "ITKImageGrid": {},
            "ITKIOBMP": {"requires": ["ITKIOImageBase"]},
            "ITKIOBioRad": {"requires": ["ITKIOImageBase"]},
            "ITKIOCSV": {"requires": ["ITKIOImageBase"]},
            "ITKIOIPL": {"requires": ["ITKIOImageBase"]},
            "ITKIOGE": {"requires": ["ITKIOIPL", "ITKIOImageBase"]},
            "ITKIOGIPL": {"requires": ["ITKIOImageBase", "zlib::zlib"]},
            "ITKIOHDF5": {"requires": ["ITKIOImageBase", "hdf5::hdf5"]},
            "ITKIOJPEG": {"requires": ["ITKIOImageBase", "libjpeg::libjpeg"]},
            "ITKIOMeshBase": {
                "requires": [
                    "ITKCommon", "ITKIOImageBase", "ITKMesh", "ITKQuadEdgeMesh",
                ],
            },
            "ITKIOMeshBYU": {"requires": ["ITKCommon", "ITKIOMeshBase"]},
            "ITKIOMeshFreeSurfer": {"requires": ["ITKCommon", "ITKIOMeshBase"]},
            "ITKIOMeshGifti": {"requires": ["ITKCommon", "ITKIOMeshBase", "ITKgiftiio"]},
            "ITKIOMeshOBJ": {"requires": ["ITKCommon", "ITKIOMeshBase"]},
            "ITKIOMeshOFF": {"requires": ["ITKCommon", "ITKIOMeshBase"]},
            "ITKIOMeshVTK": {"requires": ["ITKCommon", "ITKIOMeshBase", "double-conversion::double-conversion"]},
            "ITKIOMeta": {"requires": ["ITKIOImageBase", "ITKMetaIO"]},
            "ITKIONIFTI": {"requires": ["ITKIOImageBase", "ITKznz", "ITKniftiio", "ITKTransform"]},
            "ITKNrrdIO": {"requires": ["zlib::zlib"]},
            "ITKIONRRD": {"requires": ["ITKIOImageBase", "ITKNrrdIO"]},
            "ITKIOPNG": {"requires": ["ITKIOImageBase", "libpng::libpng"]},
            "ITKIOPhilipsREC": {"requires": ["zlib::zlib"]},
            "ITKIOSiemens": {"requires": ["ITKIOImageBase", "ITKIOIPL"]},
            "ITKIOStimulate": {"requires": ["ITKIOImageBase"]},
            "ITKIOTIFF": {"requires": ["ITKIOImageBase", "libtiff::libtiff"]},
            "ITKTransformFactory": {"requires": ["ITKCommon", "ITKTransform"]},
            "ITKIOTransformBase": {"requires": ["ITKCommon", "ITKTransform", "ITKTransformFactory"]},
            "ITKIOTransformHDF5": {"requires": ["ITKIOTransformBase", "hdf5::hdf5"]},
            "ITKIOTransformInsightLegacy": {"requires": ["ITKIOTransformBase", "double-conversion::double-conversion"]},
            "ITKIOTransformMatlab": {"requires": ["ITKIOTransformBase"]},
            "ITKIOVTK": {"requires": ["ITKIOImageBase"]},
            "ITKKLMRegionGrowing": {"requires": ["ITKCommon"]},
            "itklbfgs": {},
            "ITKMarkovRandomFieldsClassifiers": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                ],
            },
            "ITKOptimizersv4": {"requires": ["ITKOptimizers", "itklbfgs"]},
            "itkopenjpeg": {"libs": ["itkopenjpeg"]},
            "ITKQuadEdgeMeshFiltering": {"requires": ["ITKMesh"]},
            "ITKRegionGrowing": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath",
                ],
            },
            "ITKRegistrationMethodsv4": {
                "requires": [
                    "ITKCommon", "ITKOptimizersv4", "ITKStatistics", "ITKTransform",
                    "ITKSpatialObjects", "ITKPath", "ITKSmoothing", "ITKImageFeature",
                    "ITKOptimizers",
                ],
            },
            "ITKVTK": {"requires": ["ITKCommon"]},
            "ITKWatersheds": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform", "ITKSpatialObjects",
                    "ITKPath", "ITKSmoothing",
                ],
            },
            "ITKRegistrationCommon": {},
            "ITKReview": {
                "requires": [
                    "ITKCommon", "ITKStatistics", "ITKTransform", "ITKLabelMap",
                    "ITKSpatialObjects", "ITKPath", "ITKFastMarching", "ITKIOImageBase",
                    "ITKImageFeature", "ITKOptimizers", "ITKBiasCorrection",
                    "ITKDeformableMesh", "ITKDiffusionTensorImage", "ITKSmoothing",
                    "ITKFFT", "ITKIOBMP", "ITKIOBioRad", "ITKIOGDCM", "ITKIOGE",
                    "ITKIOGIPL", "ITKIOIPL", "ITKIOJPEG", "ITKIOMeta", "ITKIONIFTI",
                    "ITKIONRRD", "ITKIOPNG", "ITKIOSiemens", "ITKIOStimulate", "ITKIOTIFF",
                    "ITKIOTransformHDF5", "ITKIOTransformInsightLegacy",
                    "ITKIOTransformMatlab", "ITKIOVTK", "ITKIOXML", "ITKKLMRegionGrowing",
                    "ITKMarkovRandomFieldsClassifiers", "ITKMesh", "ITKPDEDeformableRegistration",
                    "ITKPolynomials", "ITKQuadEdgeMesh", "ITKQuadEdgeMeshFiltering",
                    "ITKRegionGrowing", "ITKVTK", "ITKWatersheds", "itkopenjpeg",
                ],
            },
            "ITKTestKernel": {
                "requires": [
                    "ITKCommon", "ITKIOImageBase", "ITKIOBMP", "ITKIOGDCM", "ITKIOGIPL",
                    "ITKIOJPEG", "ITKIOMeshBYU", "ITKIOMeshFreeSurfer", "ITKIOMeshGifti",
                    "ITKIOMeshOBJ", "ITKIOMeshOFF", "ITKIOMeshVTK", "ITKIOMeta", "ITKIONIFTI",
                    "ITKIONRRD", "ITKIOPNG", "ITKIOTIFF", "ITKIOVTK",
                ],
            },
            "ITKVideoCore": {"requires": ["ITKCommon"]},
        })
        return modules

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "ITK")
        # self.cpp_info.set_property("cmake_build_modules", [os.path.join(self._cmake_module_dir, "UseITK.cmake")])

        itk_version = tools.Version(self.version)
        lib_suffix = "-{}.{}".format(itk_version.major, itk_version.minor)

        for name, values in self._itk_components.items():
            is_header_only = values.get("header_only", False)
            system_libs = values.get("system_libs", [])
            libs = values.get("libs", [])
            requires = values.get("requires", [])
            includes = values.get("includes", [])
            self.cpp_info.components[name].set_property("cmake_target_name", name)
            self.cpp_info.components[name].builddirs.append(self._cmake_module_dir)
            self.cpp_info.components[name].includedirs.append(os.path.join("include", self._itk_subdir))
            self.cpp_info.components[name].includedirs.extend(includes)
            if not is_header_only:
                self.cpp_info.components[name].libs = ["{}{}".format(name, lib_suffix)] + libs
            self.cpp_info.components[name].system_libs = system_libs
            self.cpp_info.components[name].requires = requires

            # TODO: to remove in conan v2 once cmake_find_package* generators removed
            self.cpp_info.components[name].names["cmake_find_package"] = name
            self.cpp_info.components[name].names["cmake_find_package_multi"] = name
            # self.cpp_info.components[name].build_modules.append(os.path.join(self._cmake_module_dir, "UseITK.cmake"))
            self.cpp_info.components[name].build_modules["cmake_find_package"].append(self._module_file_rel_path)
            self.cpp_info.components[name].build_modules["cmake_find_package_multi"].append(self._module_file_rel_path)

        # TODO: to remove in conan v2 once cmake_find_package* generators removed
        self.cpp_info.names["cmake_find_package"] = "ITK"
        self.cpp_info.names["cmake_find_package_multi"] = "ITK"
