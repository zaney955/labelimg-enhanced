"""Bulk operations must not repeat global bookkeeping per resource."""
import os
import tempfile
import unittest
from unittest.mock import patch
from labelimg.files.application.operations import AnnotationFileService, FileOperationResult, SystemTrashAdapter
from labelimg.files.application.recovery import TrashIdentity, TrashedResource


class BatchOperationPerformanceTest(unittest.TestCase):
    def test_state_sort_computes_each_path_key_at_most_once(self):
        from labelimg.files import FileListProjection, FileListItemState, FileListQuery
        from labelimg.files.application.discovery import relative_image_sort_key
        items = [FileListItemState(path=os.path.abspath(f'{i}.png'), annotation_state='annotated')
                 for i in range(300, 0, -1)]
        with patch('labelimg.files.model.relative_image_sort_key', wraps=relative_image_sort_key) as key:
            projection = FileListProjection.create(os.getcwd(), items, FileListQuery(sort_key='annotation'))
            self.assertLessEqual(key.call_count, len(items))
        self.assertEqual(os.path.basename(projection.ordered_paths[0]), '1.png')

    def test_recovery_merging_uses_linear_path_work_and_keeps_first_identity(self):
        result = FileOperationResult()
        resources = [TrashedResource(os.path.abspath(f'{i}.png'), TrashIdentity('path', str(i), str(i)))
                     for i in range(200)]
        with patch('labelimg.files.application.operations.os.path.abspath', wraps=os.path.abspath) as normalize:
            for resource in resources:
                result.merge_trashed_resources([resource])
            result.merge_trashed_resources([TrashedResource(resources[0].original_path,
                TrashIdentity('path', 'new', '0'), 'latest')])
            self.assertLessEqual(normalize.call_count, 500)
        self.assertEqual(len(result.trashed_resources), 200)
        self.assertEqual(result.trashed_resources[0].identity.token, '0')
        self.assertEqual(result.trashed_resources[0].post_fingerprint, 'latest')

    def test_recycle_support_probe_is_shared_only_within_one_batch(self):
        with tempfile.TemporaryDirectory() as root:
            paths = [os.path.join(root, f'{i}.png') for i in range(6)]
            for path in paths:
                open(path, 'wb').close()
            def recycle(path):
                os.remove(path)
                return b'fake-identity'
            service = AnnotationFileService(image_dir=root, trash=SystemTrashAdapter())
            with patch('labelimg.files.application.operations.platform.system', return_value='Windows'), \
                 patch('labelimg.platform.trash.probe_recycle_support') as probe, \
                 patch('labelimg.platform.trash._delete_to_recycle_bin_raw', side_effect=recycle):
                result = service.delete_images(paths[:5])
                self.assertEqual(len(result.succeeded_images), 5)
                self.assertEqual(probe.call_count, 1)
                service.delete_images(paths[5:])
                self.assertEqual(probe.call_count, 2)
