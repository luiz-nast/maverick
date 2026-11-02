// Expõe a janela em foco no D-Bus da sessão para o Maverick: no Wayland só o
// GNOME sabe disso, e o Chrome continua se dizendo ativo depois de perder o foco.
import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `<node>
  <interface name="io.github.luiz_nast.Maverick.Focus">
    <method name="Get">
      <arg type="s" direction="out" name="wm_class"/>
      <arg type="s" direction="out" name="title"/>
      <arg type="u" direction="out" name="pid"/>
    </method>
  </interface>
</node>`;
const PATH = '/io/github/luiz_nast/Maverick/Focus';

export default class MaverickFocus extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, PATH);
    }

    disable() {
        this._dbus.unexport();
        this._dbus = null;
    }

    Get() {
        const w = global.display.focus_window;
        // PID -1 (janela X11 sem _NET_WM_PID) não cabe em uint32; 0 não bate com navegador.
        return w ? [w.get_wm_class() ?? '', w.get_title() ?? '', Math.max(w.get_pid(), 0)] : ['', '', 0];
    }
}
