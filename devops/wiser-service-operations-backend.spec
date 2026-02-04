%global debug_package %{nil}
%define _build_id_links none

Name:           wiser-service-operations-backend
Version:        1.0.0
Release:        1%{?dist}
Summary:        A FastAPI-based __SERVICE_NAME__ application
License:        Test-Licence
Source0:        %{name}-%{version}.tar.gz
BuildArch:      x86_64
Requires:       python3.11

%description
A FastAPI-based __SERVICE_NAME__ application packaged with its dependencies, designed to run using Python.

%prep
%setup -q -n __SERVICE_NAME___service

%build
echo "Nothing to build — packaged as prebuilt source with dependencies."

%install
# Prepare application folder
mkdir -p %{buildroot}/app/genzeon/hipone25/__SERVICE_NAME__
cp -r * %{buildroot}/app/genzeon/hipone25/__SERVICE_NAME__

# Ensure permissions for all files
chmod -R 0755 %{buildroot}/app/genzeon/hipone25/__SERVICE_NAME__


# ----------------------------------------------------------------------
# Systemd Units
# ----------------------------------------------------------------------
mkdir -p %{buildroot}/usr/lib/systemd/system

# ---------------- FASTAPI SERVICE ----------------
cat > %{buildroot}/usr/lib/systemd/system/__SERVICE_NAME__.service <<'SERVICE'
[Unit]
Description=FastAPI __SERVICE_NAME__ Application Service
After=network.target

[Service]
Environment="ETCD_HOST=punnor1"
Environment="ETCD_PORT=2379"
Environment="INSTANCE_ID=vlm-service-1"
Environment="SERVICE_TAGS=core,stateless"
Environment="SERVICE_NAME=vlm-service"
Environment="SERVICE_PORT=5135"
Environment="SERVICE_DESCRIPTION=An API interface to interact with Vision Language Model."
Environment="PYTHONPATH=/app/genzeon/hipone25/__SERVICE_NAME__:/app/genzeon/hipone25/__SERVICE_NAME__/dependencies_unpacked:/app/genzeon/libs/"
Environment="ROLE=api"

ExecStart=/usr/bin/python3.11 /app/genzeon/hipone25/__SERVICE_NAME__/app/main.py
WorkingDirectory=/app/genzeon/hipone25/__SERVICE_NAME__
Restart=on-failure
RestartSec=5
User=zx09023
Group=uxgGenzeon_Adm
RuntimeDirectory=__SERVICE_NAME__
RuntimeDirectoryMode=0755
PIDFile=/run/__SERVICE_NAME__/__SERVICE_NAME__.pid
ExecStartPost=/bin/bash -c "echo $MAINPID > /run/__SERVICE_NAME__/__SERVICE_NAME__.pid && chmod 666 /run/__SERVICE_NAME__/__SERVICE_NAME__.pid"
Type=simple

[Install]
WantedBy=multi-user.target
SERVICE

%post
# Determine environment from hostname
host=$(hostname)
env_char=$(echo "$host" | rev | cut -c3)  # third-last character
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
        echo "Unknown environment for hostname $host. Defaulting to zx09023."
        app_user="zx09023"
        etcd_host="punnor1"
        etcd_port="2379"
        ;;
esac
app_group="uxgGenzeon_Adm"
echo "Detected environment char '$env_char' from hostname '$host'."
echo "Setting service user to ${app_user}:${app_group} and ETCD to ${etcd_host}:${etcd_port}."

# Update User/Group in service file
svc_file="/usr/lib/systemd/system/__SERVICE_NAME__.service"
if grep -q '^User=' "$svc_file"; then
    sed -i "s|^User=.*|User=${app_user}|" "$svc_file"
else
    sed -i "/^\[Service\]/a User=${app_user}" "$svc_file"
fi
if grep -q '^Group=' "$svc_file"; then
    sed -i "s|^Group=.*|Group=${app_group}|" "$svc_file"
else
    sed -i "/^\[Service\]/a Group=${app_group}" "$svc_file"
fi

# Update ETCD_HOST and ETCD_PORT in service file
sed -i "/^Environment=\"ETCD_HOST=/c Environment=\"ETCD_HOST=${etcd_host}\"" "$svc_file"
sed -i "/^Environment=\"ETCD_PORT=/c Environment=\"ETCD_PORT=${etcd_port}\"" "$svc_file"

# Ensure correct file permissions & ownership
chmod -R 0755 /app/genzeon/hipone25/__SERVICE_NAME__
chown -R "${app_user}:${app_group}" /app/genzeon/hipone25/__SERVICE_NAME__

# Dependencies unpacking
mkdir -p /app/genzeon/hipone25/__SERVICE_NAME__/dependencies_unpacked
chown -R "${app_user}:${app_group}" /app/genzeon/hipone25/__SERVICE_NAME__/dependencies_unpacked

if ls /app/genzeon/hipone25/__SERVICE_NAME__/dependencies/*.whl > /dev/null 2>&1; then
    for whl in /app/genzeon/hipone25/__SERVICE_NAME__/dependencies/*.whl; do
        /usr/bin/python3.11 -m pip install --no-deps --target /app/genzeon/hipone25/__SERVICE_NAME__/dependencies_unpacked $whl
    done
else
    echo "⚠️  No .whl files found in dependencies/ — skipping."
fi

# Reload systemd (no auto-start)
systemctl daemon-reload
echo "vlm-service installed. API and workers will NOT auto-start."

%preun
if [ "$1" = "0" ]; then
    systemctl stop __SERVICE_NAME__.service || true
    systemctl disable __SERVICE_NAME__.service || true
fi

%postun
rm -rf /app/genzeon/hipone25/__SERVICE_NAME__

%files
/app/genzeon/hipone25/__SERVICE_NAME__
/usr/lib/systemd/system/__SERVICE_NAME__.service
