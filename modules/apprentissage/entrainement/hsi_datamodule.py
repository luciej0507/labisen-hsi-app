from anomalib.data import AnomalibDataModule
from anomalib.data import ImageBatch
from torch.utils.data import DataLoader
import torch
from modules.apprentissage.entrainement.dataloader_patches import HSIDataset




class HSIDataModule(AnomalibDataModule):
    """
    Gère la création et la mise à disposition des DataLoaders
    pour les phases d'entraînement, validation et test,
    dans le format attendu par Anomalib.
    """
    def __init__(self, train_csv, val_csv=None, test_csv=None, batch_size=128, num_workers=4):       # batch_size=64
        # Appel obligatoire du constructeur parent pour initialiser
        # tout ce qu'AnomalibDataModule a besoin en interne
        super().__init__(
            train_batch_size=batch_size,
            eval_batch_size=batch_size,
            num_workers=num_workers,
            # image_size=(300, 100),    # pas accepter dans cette version d'Anomalib
        )
        
        # Stockage des paramètres pour les utiliser dans setup() et les dataloaders
        self.train_csv   = train_csv
        self.test_csv    = test_csv
        self.val_csv     = val_csv
        self.batch_size  = batch_size
        self.num_workers = num_workers


    def _setup(self, stage=None):
        """
        Instancie les datasets selon la phase d'entraînement.
        Appelé automatiquement par le Trainer avant chaque phase.

        Args:
            stage : 'fit' (entraînement + validation), 'test', ou None (tout instancier)
        """
        # on n'instancie que ce qui est nécessaire selon le stage
        if stage in ("fit", None):
            # Dataset d'entraînement : patches normaux uniquement (label=0)
            self.train_data = HSIDataset(csv_file=self.train_csv)

            # Dataset de validation : patches normaux (labels 0)
            self.val_data  = HSIDataset(csv_file=self.val_csv)
            
            # pour analyser la distribution des données
            self.test_data  = HSIDataset(csv_file=self.test_csv)

        if stage in ("test", None):
            # Dataset de test : patches normaux + anomalies (labels 0 et 1)
            self.test_data  = HSIDataset(csv_file=self.test_csv)
        
        
    def _make_dataloader(self, dataset, shuffle=False):
        """Factorisation : évite de répéter les mêmes paramètres plusieurs fois."""
        return DataLoader(
            dataset,
            batch_size  = self.eval_batch_size,
            shuffle     = shuffle,
            num_workers = self.num_workers,
            pin_memory  = torch.cuda.is_available(),
            collate_fn  = ImageBatch.collate,
        ) 

    def train_dataloader(self):
        return self._make_dataloader(self.train_data, shuffle=True)

    def val_dataloader(self):
        return self._make_dataloader(self.val_data)

    def test_dataloader(self):
        return self._make_dataloader(self.test_data)

