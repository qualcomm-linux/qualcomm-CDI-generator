project('Qualcomm CDI generator', 'c',
        version : '0.0',
        license : [ 'BSD-3-Clause' ],
        license_files: [ 'LICENSE.txt' ]
        )

systemd = dependency('systemd')
systemd_system_unit_dir = systemd.get_variable(pkgconfig : 'systemdsystemunitdir' )

install_data('qualcomm-cdi-generator.service', install_dir : systemd_system_unit_dir)
install_data('qualcomm-cdi-generator.py', install_dir : join_paths(get_option('prefix'), get_option('sbindir')), install_mode: 'rwxr-xr-x')

summary({'Systemd units installation......': systemd_system_unit_dir,
         'Install prefix..................': get_option('prefix'),
        }, section: 'General', bool_yn: true)

