{
  lib
, buildPythonPackage
, setuptools
, udisks-monitor
, src
}:
buildPythonPackage rec {
  pname = "unmount-image";
  version = "0.1.2";
  pyproject = true;

  inherit src;

  nativeBuildInputs = [ setuptools ];
  propagatedBuildInputs = [ udisks-monitor ];

  doCheck = false;
  pythonImportsCheck = [ "unmount_image" ];

  meta = with lib; {
    description = "Disk image unmount and detach via udisksctl (Linux)";
    homepage = "https://github.com/MBanucu/unmount-image";
    license = licenses.gpl3Only;
    maintainers = with maintainers; [ ];
  };
}
