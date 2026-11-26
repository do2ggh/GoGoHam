#
# GoGoHam – Contest-Logger für Linux (openSUSE und Fedora)
# © 2026 Franz, DO2GGH · GPL-3.0-only
#
# openSUSE: nur eine Python-Fassung bauen (Tumbleweed: python3, Leap 16: python313)
%if 0%{?suse_version} >= 1650
%define pythons python3
%else
%define pythons python313
%endif
Name:           gogoham
Version:        0.9.2
Release:        0
Summary:        Contest logger for Linux with live dupe check and live score
License:        GPL-3.0-only
URL:            https://github.com/do2ggh/GoGoHam
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  desktop-file-utils
BuildRequires:  hicolor-icon-theme
%if 0%{?suse_version}
BuildRequires:  fdupes
BuildRequires:  python-rpm-macros
BuildRequires:  %{python_module pip}
BuildRequires:  %{python_module setuptools >= 77}
BuildRequires:  %{python_module wheel}
# openSUSE: sqlite3 steckt im vollen Python-Paket, nicht in -base (Pakettest 2026-11-13)
%if 0%{?suse_version} >= 1650
Requires:       python3
Requires:       python3-pyside6
%else
Requires:       python313
Requires:       python313-pyside6
%endif
Requires:       python3-numpy
Requires:       hamlib
Recommends:     speech-dispatcher
Recommends:     qt6-translations
%else
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pip
BuildRequires:  python3-setuptools >= 77
BuildRequires:  python3-wheel
Requires:       python3-pyside6
Requires:       python3-numpy
Requires:       hamlib
Recommends:     speech-dispatcher
Recommends:     qt6-qttranslations
%endif
Requires:       hicolor-icon-theme

%description
GoGoHam is a contest logger for Linux: fast entry, live dupe check, live points and
multipliers while typing, CAT control via Hamlib, QSOs from WS and other FT8 programs,
Cabrillo and ADIF export, DX cluster with band map, grayline map and a practice mode.
50 HF and VHF contests as readable rule files. German and English.

%prep
%autosetup -p1

%build
%pyproject_wheel

%install
%pyproject_install
# 0.10.25: USB-Freigabe (uaccess) – Funkgerät-Kabel, GPS, WinKeyer ohne Gruppe nutzbar
install -Dm644 gogoham/assets/70-gogoham.rules %{buildroot}%{_prefix}/lib/udev/rules.d/70-gogoham.rules
%if 0%{?suse_version}
%python_expand %fdupes %{buildroot}%{$python_sitelib}
%endif
desktop-file-validate %{buildroot}%{_datadir}/applications/gogoham.desktop

%check
# Kurzprüfung: Paket vollständig? (alle Tests laufen bei jedem Hochladen auf GitHub)
%if 0%{?suse_version}
%python_expand PYTHONPATH=%{buildroot}%{$python_sitelib} $python -c "import gogoham, pathlib; r = pathlib.Path(gogoham.__file__).parent; assert len(list((r / 'rules').glob('*.json'))) >= 50"
%else
PYTHONPATH=%{buildroot}%{python3_sitelib} %{python3} -c "import gogoham, pathlib; r = pathlib.Path(gogoham.__file__).parent; assert len(list((r / 'rules').glob('*.json'))) >= 50"
%endif

%files
%license LICENSE ADDITIONAL-TERMS.md THIRD-PARTY.md
%doc README.md README.en.md CHANGELOG.md
%{_bindir}/gogoham
%if 0%{?suse_version}
%{python_sitelib}/gogoham
%{python_sitelib}/gogoham-%{version}.dist-info
%else
%{python3_sitelib}/gogoham
%{python3_sitelib}/gogoham-%{version}.dist-info
%endif
%{_datadir}/applications/gogoham.desktop
%{_datadir}/metainfo/io.github.do2ggh.GoGoHam.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/gogoham.png
%{_prefix}/lib/udev/rules.d/70-gogoham.rules

%changelog
