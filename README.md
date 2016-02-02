dmf-device-ui
=============

`dmf-device-ui` is a graphical user interface to control a digital
microfluidics control system (such as the MicroDrop/DropBot system described in
detail in [Fobel et al., Appl. Phys. Lett. 102, 193513 (2013)][2]).

If you use this software in work that you publish, please cite as appropriate.

Installation
============

## Automatic installation ##

The `dmf-device-ui` package is a dependency of the `dmf_device_ui_plugin`
MicroDrop plugin, and will be installed automatically if the
`dmf_device_ui_plugin` plugin is installed.

## Manual installation ##

    pip install --find-links http://192.99.4.95/wheels --trusted-host 192.99.4.95 dmf-device-ui

The `--find-links` and `--trusted-host` are required to provide binary Gtk2
dependencies as wheels.  Visit http://192.99.4.95/wheels to browse the
contents.

The wheels server at `192.99.4.95` is maintained by Christian Fobel
<christian@fobel.net>.


Usage
=====

The `dmf-device-ui` GUI will be launched automatically from MicroDrop if the
`dmf_device_ui_plugin` plugin is installed.


## Actuate electrodes ##

![Actuate electrodes][actuate-electrodes]

## Draw route ##

Click and drag to draw route following mouse cursor.

![Draw route][draw-route]

## Draw mix ##

End a route at the starting point to draw a mixing route/cycle.

![Draw mix][draw-mix]

## Auto route ##

Hold `<alt>`, click on source electrode, and release on target electrode to
automatically find a route between the source and target.

![Auto route][auto-route]

## Adjust layer alpha ##

The alpha/opacity of each layer (e.g., connections, electrode shapes, labels)
can be adjusted independently.

![Adjust layer alpha][adjust-layer-alpha]


[1]: http://microfluidics.utoronto.ca/microdrop
[2]: http://dx.doi.org/10.1063/1.4807118
[3]: https://pypi.python.org/pypi/microdrop

[actuate-electrodes]: docs/static/images/actuate-electrodes.gif
[draw-route]: docs/static/images/draw-route.gif
[draw-mix]: docs/static/images/draw-mix.gif
[auto-route]: docs/static/images/auto-route.gif
[adjust-layer-alpha]: docs/static/images/adjust-layer-alpha.gif


Credits
=======

Christian Fobel <christian@fobel.net>
