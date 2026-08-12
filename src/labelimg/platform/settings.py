import pickle
import os


class _SettingsUnpickler(pickle.Unpickler):
    """Load settings written before modules moved out of top-level ``libs``."""

    def find_class(self, module, name):
        if (
            module in ('libs.labelFile', 'labelimg.labelFile')
            and name == 'LabelFileFormat'
        ):
            from labelimg.annotations.domain.model import AnnotationFormat

            return AnnotationFormat
        return super().find_class(module, name)


class Settings(object):
    def __init__(self):
        config_dir = os.environ.get(
            'LABELIMG_CONFIG_DIR',
            os.path.expanduser("~"),
        )
        self.data = {}
        self.path = os.path.join(config_dir, '.labelImgSettings.pkl')

    def __setitem__(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return default

    def save(self):
        if self.path:
            with open(self.path, 'wb') as f:
                pickle.dump(self.data, f, pickle.HIGHEST_PROTOCOL)
                return True
        return False

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'rb') as f:
                    self.data = _SettingsUnpickler(f).load()
                    return True
        except:
            print('Loading setting failed')
        return False

    def reset(self):
        if os.path.exists(self.path):
            os.remove(self.path)
            print('Remove setting pkl file ${0}'.format(self.path))
        self.data = {}
        self.path = None
