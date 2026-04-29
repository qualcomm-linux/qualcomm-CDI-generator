project('Qualcomm CDI generator', 'c',
        version : '0.4',
        license : [ 'BSD-3-Clause' ],
        license_files: [ 'LICENSE.txt' ]
        )

systemd = dependency('systemd')
systemd_system_unit_dir = systemd.get_variable(pkgconfig : 'systemdsystemunitdir' )
systemd_system_preset_dir = systemd.get_variable(pkgconfig : 'systemdsystempresetdir' )

install_data('qualcomm-cdi-generator.service', install_dir : systemd_system_unit_dir)
install_data('10-qualcomm-cdi-generator.preset', install_dir : systemd_system_preset_dir)
install_data('qualcomm-cdi-generator', install_dir : join_paths(get_option('prefix'), get_option('sbindir')), install_mode: 'rwxr-xr-x')
install_man('man/qualcomm-cdi-generator.8')

summary({'Systemd units installation......': systemd_system_unit_dir,
         'Systemd presets installation....': systemd_system_preset_dir,
         'Install prefix..................': get_option('prefix'),
        }, section: 'General', bool_yn: true)

