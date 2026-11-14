"""
Entraînement FastFlow (HSI, anomalib), lancé par l'application Streamlit.

Utilisation : python fastflow_mlflow.py --dossier <dossier_du_run>

Le dossier du run contient config.json, écrit par l'application. Le script y
écrit status.json (état lu par Streamlit) et resultats/ (checkpoints, logs).
Le GPU est choisi par l'application avec la variable CUDA_VISIBLE_DEVICES : le
script ne voit donc qu'un seul GPU, toujours numéroté 0.

Les fichiers hsi_datamodule.py et dataloader_patches.py doivent être dans le
même dossier que ce script.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import mlflow
import mlflow.pytorch
import pandas as pd
import torch
from anomalib.engine import Engine
from anomalib.metrics import Evaluator
from anomalib.models import Fastflow
from lightning.pytorch.callbacks import Callback, ModelCheckpoint
from lightning.pytorch.loggers import CSVLogger, MLFlowLogger

from hsi_datamodule import HSIDataModule

NOM_EXPERIENCE = "test_mlflow_streamlit_fastflow"
NOM_MODELE_REGISTRY = "fastflow_streamlit"

# Informations ajoutées à chaque écriture du statut : identifiants du run
# MLflow (pour le lien dans Streamlit) et historique de la loss (pour la courbe)
INFOS_FIXES = {}


def parse_args():
    parser = argparse.ArgumentParser(description="Entraînement FastFlow (HSI, anomalib)")
    parser.add_argument("--dossier", type=str, required=True,
                        help="Dossier du run (contient config.json)")
    return parser.parse_args()


def write_status(status_file: Path, **kwargs):
    """Écrit l'état courant de l'entraînement dans un fichier JSON lu par Streamlit."""
    payload = {"updated_at": datetime.now().isoformat(), **INFOS_FIXES, **kwargs}
    temporaire = status_file.with_suffix(".tmp")
    try:
        # Écriture puis remplacement : Streamlit ne lit jamais un fichier à moitié écrit
        temporaire.write_text(json.dumps(payload))
        os.replace(temporaire, status_file)
    except Exception as e:
        print(f"[WARN] Impossible d'écrire le status file : {e}", flush=True)


def preparer_csv(chemin, labels, racine_patches, sortie: Path) -> Path:
    """
    Copie le CSV en ne gardant que les labels voulus (None = tous les labels).

    Les chemins des fichiers de patches (colonnes path_dat et path_npy) sont
    relatifs à racine_patches dans le CSV d'origine : on les rend absolus, car
    la copie est rangée dans un autre dossier.
    """
    df = pd.read_csv(chemin)
    if labels is not None:
        df = df[df["label"].isin(labels)]
    if df.empty:
        raise ValueError(f"Aucun patch à utiliser dans {chemin} (labels retenus : {labels})")

    # Un chemin déjà absolu reste inchangé
    for colonne in ("path_dat", "path_npy"):
        df[colonne] = df[colonne].map(lambda p: str(Path(racine_patches) / p))

    df.to_csv(sortie, index=False)
    return sortie


# Callback personnalisé : affiche la loss à la fin de chaque epoch, met à jour
# le fichier de statut lu par Streamlit et loggue le meilleur modèle dans MLflow
class EpochLogger(Callback):
    def __init__(self, status_file: Path, max_epochs: int, checkpoint_callback: ModelCheckpoint,
                 mlflow_logger: MLFlowLogger, registered_model_name: str):
        self.status_file = status_file
        self.max_epochs = max_epochs
        self.checkpoint_callback = checkpoint_callback
        self.mlflow_logger = mlflow_logger
        self.registered_model_name = registered_model_name
        self.best_score_logged = None  # dernier score déjà loggé dans MLflow

    def on_train_start(self, trainer, pl_module):
        write_status(self.status_file, state="running", epoch=0,
                     total_epochs=self.max_epochs, loss=None)

    def on_train_epoch_end(self, trainer, pl_module):
        loss = trainer.callback_metrics.get("train_loss_epoch", "N/A")
        epoch = trainer.current_epoch + 1
        total = trainer.max_epochs
        if loss != "N/A":
            print(f"[Epoch {epoch}/{total}] train_loss = {loss:.4f}", flush=True)
            loss_value = float(loss)
            INFOS_FIXES["historique_loss"].append(loss_value)
        else:
            print(f"[Epoch {epoch}/{total}] train_loss = N/A", flush=True)
            loss_value = None

        write_status(self.status_file, state="running", epoch=epoch,
                     total_epochs=total, loss=loss_value)

        # Log dans MLflow uniquement si le score s'est amélioré
        current_best = self.checkpoint_callback.best_model_score
        if current_best is not None:
            current_best = float(current_best)
            if self.best_score_logged is None or current_best < self.best_score_logged:
                self.best_score_logged = current_best
                try:
                    mlflow.pytorch.log_model(
                        pytorch_model=pl_module,
                        artifact_path="model",
                        registered_model_name=self.registered_model_name,
                        serialization_format="pickle",
                        # Ne pas attendre 300 s la confirmation d'enregistrement
                        # dans le registry : cela retardait la fin du process
                        # (et donc la libération du GPU).
                        await_registration_for=10,
                    )
                    print(f"[INFO] Nouveau meilleur modèle loggé dans MLflow (loss={current_best:.4f})", flush=True)
                except Exception as e:
                    print(f"[WARN] Échec du log du meilleur modèle : {e}", flush=True)


def main():
    args = parse_args()
    dossier = Path(args.dossier)
    status_file = dossier / "status.json"
    config = json.loads((dossier / "config.json").read_text())

    try:
        if config["modele"] != "FastFlow":
            raise ValueError(f"Modèle non pris en charge : {config['modele']}")

        hyperparametres = config["hyperparametres"]
        generaux = config["parametres_generaux"]

        # --- CSV : on ne garde que les labels retenus (0 en non supervisé) ---
        print("[INFO] Préparation des CSV...", flush=True)
        dossier_csv = dossier / "csv"
        dossier_csv.mkdir(exist_ok=True)
        labels = config["labels_retenus"]
        racine = config["racine_patches"]
        train_csv = preparer_csv(config["csv"]["train"], labels, racine, dossier_csv / "train.csv")
        if "val" in config["csv"]:
            val_csv = preparer_csv(config["csv"]["val"], labels, racine, dossier_csv / "val.csv")
        else:
            # Validation désactivée : le DataModule veut quand même un CSV
            # pour chaque split, ils ne seront pas utilisés
            val_csv = train_csv
        test_csv = train_csv

        # --- Dossier des résultats (checkpoints, logs) ---
        save_dir = dossier / "resultats"
        save_dir.mkdir(exist_ok=True)

        # --- GPU : un seul est visible (choisi par l'application) ---
        accelerator = "gpu" if torch.cuda.is_available() else "cpu"
        devices = [0]

        # --- MLflow : un seul run, ouvert avant l'entraînement ---
        # Ce run est utilisé à la fois par Lightning (métriques, hyperparamètres)
        # et par les appels mlflow.pytorch.log_model() dans EpochLogger.
        mlflow.set_tracking_uri(config["mlflow_uri"])
        mlflow.set_experiment(NOM_EXPERIENCE)
        mlflow_logger = MLFlowLogger(
            experiment_name=NOM_EXPERIENCE,
            tracking_uri=config["mlflow_uri"],
            run_name=f"fastflow_{datetime.now().strftime('%Y%m%d_%H%M')}",
        )
        mlflow.start_run(run_id=mlflow_logger.run_id)

        # Identifiants transmis à Streamlit pour le lien vers MLflow
        INFOS_FIXES.update(
            run_id=mlflow_logger.run_id,
            experiment_id=mlflow_logger.experiment_id,
            historique_loss=[],
        )
        write_status(status_file, state="starting")

        # --- DataModule ---
        print("[INFO] Chargement des datasets...", flush=True)
        datamodule = HSIDataModule(
            train_csv=train_csv,
            test_csv=test_csv,
            val_csv=val_csv,
            batch_size=generaux["batch_size"],
            num_workers=generaux["num_workers"],
        )

        # --- Modèle : les hyperparamètres choisis dans l'application ---
        print("[INFO] Chargement du modèle FastFlow...", flush=True)
        model = Fastflow(**hyperparametres, visualizer=False)
        model.evaluator = Evaluator(val_metrics=[], test_metrics=[])

        # --- Sauvegarde du meilleur modèle ---
        checkpoint_callback = ModelCheckpoint(
            monitor="train_loss_epoch",
            mode="min",
            save_top_k=1,
            save_last=True,
            filename="best_model_fastflow-{epoch:03d}",
        )

        # --- Engine ---
        engine = Engine(
            max_epochs=generaux["epochs"],
            accelerator=accelerator,
            devices=devices,
            default_root_dir=save_dir,
            logger=[CSVLogger(save_dir=save_dir, name="csv_logs"), mlflow_logger],
            callbacks=[
                checkpoint_callback,
                EpochLogger(status_file, generaux["epochs"], checkpoint_callback,
                            mlflow_logger, registered_model_name=NOM_MODELE_REGISTRY),
            ],
            limit_val_batches=1.0 if generaux["validation"] else 0,
            enable_progress_bar=False,  # garde le journal lisible dans Streamlit
        )

        # --- Hyperparamètres et configuration envoyés à MLflow ---
        mlflow_logger.log_hyperparams({
            **hyperparametres,
            **generaux,
            "modele": config["modele"],
            "type_apprentissage": config["type_apprentissage"],
            "split": config["split"],
            "format_patches": config["format_patches"],
            "fraction_csv": config["fraction_csv"],
            "dataset": config["dataset"],
        })
        mlflow_logger.experiment.log_artifact(mlflow_logger.run_id, str(dossier / "config.json"))

        # --- Entraînement ---
        print(f"[INFO] Démarrage de l'entraînement : {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}", flush=True)
        engine.fit(model=model, datamodule=datamodule)
        print(f"[INFO] Entraînement terminé avec succès ! {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}", flush=True)

        best_ckpt = checkpoint_callback.best_model_path
        if best_ckpt:
            mlflow_logger.experiment.log_artifact(mlflow_logger.run_id, best_ckpt)
            print(f"[INFO] Checkpoint loggé dans MLflow : {best_ckpt}", flush=True)

        mlflow_logger.finalize("success")
        write_status(status_file, state="done", epoch=generaux["epochs"],
                     total_epochs=generaux["epochs"],
                     loss=(INFOS_FIXES["historique_loss"] or [None])[-1])

    except Exception as e:
        print(f"[ERREUR] Problème pendant l'entraînement : {e}", flush=True)
        write_status(status_file, state="error", message=str(e))
        # Clôturer le run (statut FAILED) pour ne pas laisser un run "orphelin"
        # affiché comme actif dans l'UI MLflow
        try:
            mlflow.end_run(status="FAILED")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()