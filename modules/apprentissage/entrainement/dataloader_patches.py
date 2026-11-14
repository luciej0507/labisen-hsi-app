from anomalib.data import AnomalibDataset
from anomalib.data import ImageItem
import pandas as pd
import numpy as np
import torch



# fonction extraite de dataloader.py pour normaliser les cubes par bande
def normalize_cube_per_band(cube):
    """
    cube shape: (B, H, W)
    Normalisation min-max par bande entre 0 et 1
    """
    
    # min et max calculés sur chaque bande (sur axes H et W)
    min_vals = cube.min(axis=(1, 2), keepdims=True)  # shape (B,1,1)
    max_vals = cube.max(axis=(1, 2), keepdims=True)  # shape (B,1,1)
    
    denom = max_vals - min_vals
    denom[denom == 0] = 1  # éviter division par zéro ()
    
    cube_norm = (cube - min_vals) / denom   # chaque valeur est ramenée entre 0 et 1
    
    return cube_norm.astype(np.float32)     # et non float64 : c'est ce qui est attendu par PyTorch



# Dataloader personnalisé pour les patches, compatible avec anomalib
class HSIDataset(AnomalibDataset):
    def __init__(self, csv_file, transform=None):
        super().__init__()
        self.transform = transform
        self.cache = {}
        self.label_map = {'normal': 0, 'anormal': 1}
        
        df = pd.read_csv(csv_file)
        # Colonnes obligatoires pour AnomalibDataset
        df['image_path'] = df['path_dat']
        df['split'] = 'train'
        df['label_index'] = df['label']
        self.samples = df
    
    
    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        # Lecture de la ligne correspondante dans le CSV
        row = self.samples.iloc[idx]
        path_dat = row['path_dat']
        path_npy = row['path_npy']
        index_in_tensor = int(row['index'])
        label = int(row['label'])

        # Chargement du shape depuis le .npy
        patches_shape = np.load(path_npy)
        patches_shape = tuple(patches_shape)
        
        # Chargement du tableau de patches via memmap (lecture sans tout charger en RAM)
        patches_memmap = np.memmap(path_dat, dtype='float32', mode='r', shape=patches_shape)
        
        # Réorganisation des axes ((B, 300, 1, 100) devient (B, 1, 300, 100))
        patches_memmap = np.transpose(patches_memmap, (0, 2, 1, 3))
        
        # Extraction du patch à l'index voulu (shape: (1, 300, 100))
        tensor = patches_memmap[index_in_tensor]  # numpy array, type np.float32
                
        tensor = normalize_cube_per_band(tensor)
                
        # Transformations optionnelles
        if self.transform:
            tensor = self.transform(tensor)

        # AJOUT 1 : conversion numpy en tensor torch
        tensor = torch.tensor(tensor, dtype=torch.float32)       # torch.Tensor, prêt pour le modèle
        
        # AJOUT : squeeze pour retirer la dimension 1 superflue, puis repeat pour passer à 3 canaux
        tensor = tensor.squeeze(0)       # shape: (300, 100)
        tensor = tensor.unsqueeze(0)     # shape: (1, 300, 100)

        # AJOUT 2 : repeat pour passer de 1 à 3 canaux
        # pour compatibilité avec les modèles pré-entraînés qui attendent 3 canaux RGB
        tensor = tensor.repeat(3, 1, 1)           # shape: (3, 300, 100)
        
        # AJOUT 3 : retourner un dictionnaire (au lieu d'un tuple) attendu par anomalib
        return ImageItem(
            image = tensor,
            gt_label = torch.tensor(label, dtype=torch.long),
            image_path = path_dat,
        )