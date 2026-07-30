# Validate in isolation before replacing the DL installation

LabelImg Enhanced will be built and tested in a dedicated development environment before deployment. After validation, the customized LabelImg files currently installed in the `DL` Conda environment will be backed up and the old `labelImg` distribution will be replaced with the verified `labelimg-enhanced` wheel, avoiding conflicting packages and `labelImg` console entry points while retaining a rollback path.
