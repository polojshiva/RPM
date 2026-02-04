%global debug_package %{nil}
%define _build_id_links none
%global service_name %{name}

Name:           wiser-service-operations-backend
Version:        1.0.0
Release:        1%{?dist}
Summary:        A FastAPI-based %{service_name} application
License:        Test-Licence
URL:            internal
Source0:        %{name}-%{version}.tar.gz
BuildArch:      x86_64
Requires:       python3.11

%description
A FastAPI-based %{service_name} application packaged with its dependencies,
designed to run using Python.

%prep
%setup -q

%build
echo "Nothing to build — packaged as prebuilt source with dependencies."

%install
# Application directory
mkdir -p %{buildroot}/app/genzeon/hipone25/%{service_name}
cp -r * %{buildroot}/app/genzeon/hipone25/%{service_name}

chmod -R 0755 %{buildroot}/app/genzeon/hipone25/%{service_name}

# ----------------------------------------------------------------------
# Systemd unit
# ----------------------------------------------------------------------
mkdir -p %{buildroot}/usr/lib/systemd/system

cat > %{buildroot}/usr/lib/systemd/system/%{service_name}.service <<'SERVICE'
[Unit]
Description=FastAPI %{service_name} Application Service
After=network.target

[Service]
Environment="ETCD_HOST=punnor1"
Environment="ETCD_PORT=2379"
Environment="INSTANCE_ID=vlm-service-1"
Environment="SERVICE_TAGS=core,stateless"
Environment="SERVICE_NAME=vlm-service"
Environment="SERVICE_PORT=5135"
Environment="SERVICE_DESCRIPTION=An API interface to interact with Vision Language Model."
Environment="PYTHONPATH=/app/genzeon/hipone25/%{service_name}:/app/genzeon/hipone25/%{service_name}/dependencies_unpacked:/app/genzeon/libs/"
Environment="ROLE=api"

ExecStart=/usr/bin/python3.11 /app/genzeon/hipone25/%{service_name}/app/main.py
WorkingDirectory=/app/genzeon/hipone25/%{service_name}
Restart=on-failure
RestartSec=5
User=zx09023
Group=uxgGenzeon_Adm
RuntimeDirectory=%{service_name}
RuntimeDirectoryMode=0755
PIDFile=/run/%{service_name}/%{service_name}.pid
ExecStartPost=/bin/bash -c "echo \$MAINPID > /run/%{service_name}/%{service_name}.pid && chmod 666 /run/%{service_name}/%{service_name}.pid"
Type=simple

[Install]
WantedBy=multi-user.target
SERVICE

%post
host=$(hostname)
env_char=$(echo "$host" | rev | cut -c3)

case "$env_char" in
    d|D)
        app_user="zx09023"
        etcd_host="nhfirvlgzngwd00"
        etcd_port="5155"
        ;;
    t|T)
        app_user="zx09160"
        etcd_host="nhfirvlgzngwt00"
        etcd_port="5155"
        ;;
    p|P)
        app_user="zx09205"
        etcd_host="nhfirvlgzngwp00"
        etcd_port="5155"
        ;;
    *)
        echo "Unknown environment. Using defaults."
        app_user="zx09023"
        etcd_host="punnor1"
        etcd_port="2379"
        ;;
esac

app_group="uxgGenzeon_Adm"
svc_file="/usr/lib/systemd/system/%{service_name}.service"

sed -i "s|^User=.*|User=${app_user}|" "$svc_file"
sed -i "s|^Group=.*|Group=${app_group}|" "$svc_file"
sed -i "s|^Environment=\"ETCD_HOST=.*|Environment=\"ETCD_HOST=${etcd_host}\"|" "$svc_file"
sed -i "s|^Environment=\"ETCD_PORT=.*|Environment=\"ETCD_PORT=${etcd_port}\"|" "$svc_file"

chmod -R 0755 /app/genzeon/hipone25/%{service_name}
chown -R "${app_user}:${app_group}" /app/genzeon/hipone25/%{service_name}

mkdir -p /app/genzeon/hipone25/%{service_name}/dependencies_unpacked
chown -R "${app_user}:${app_group}" /app/genzeon/hipone25/%{service_name}/dependencies_unpacked

if ls /app/genzeon/hipone25/%{service_name}/dependencies/*.whl >/dev/null 2>&1; then
    for whl in /app/genzeon/hipone25/%{service_name}/dependencies/*.whl; do
        /usr/bin/python3.11 -m pip install --no-deps --target \
          /app/genzeon/hipone25/%{service_name}/dependencies_unpacked "$whl"
    done
else
    echo "No wheel files found — skipping dependency install."
fi

systemctl daemon-reload
echo "%{service_name} installed (not auto-started)."

%preun
if [ "$1" = "0" ]; then
    systemctl stop %{service_name}.service || true
    systemctl disable %{service_name}.service || true
fi

%postun
rm -rf /app/genzeon/hipone25/%{service_name}

%files
/app/genzeon/hipone25/%{service_name}
/usr/lib/systemd/system/%{service_name}.service
