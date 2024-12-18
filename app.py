import streamlit as st
import pandas as pd
from io import BytesIO

# Imports pour Google Search Console
import searchconsole
from apiclient import discovery
from google_auth_oauthlib.flow import Flow

# Import pour OpenAI
import openai

###############################################################################
# Configuration de la page Streamlit
###############################################################################

st.set_page_config(
    layout="centered",
    page_title="GSC Scorecard",
    page_icon="🔌📝"
)

###############################################################################
# Constantes
###############################################################################

ROW_CAP = 25000  # Limite de lignes pour les requêtes GSC
TOP_N_RESULTS = 50  # Nombre d'éléments à afficher

###############################################################################
# Fonctions auxiliaires
###############################################################################

def get_search_console_data(webproperty, search_type, selected_days, dimensions):
    """
    Récupère les données de la Google Search Console en fonction des paramètres spécifiés.
    """
    q = webproperty.query.search_type(search_type).range("today", days=selected_days)
    
    for dim in dimensions:
        if dim != "none":
            q = q.dimension(dim)
    
    q = q.limit(ROW_CAP)
    report = q.get().to_dataframe()
    return report

def categorize_with_openai(keyword, candidate_labels):
    """
    Catégorise un mot-clé en utilisant l'API OpenAI.
    """
    prompt = (
        f"Étant donné les catégories suivantes, classez le mot-clé suivant dans la catégorie appropriée "
        f"en fonction de son sens :\n\nMot-clé : {keyword}\nCatégories :\n- " +
        "\n- ".join(candidate_labels) +
        "\n\nFournissez uniquement la catégorie, sans autre texte."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Vous êtes un assistant utile."},
                {"role": "user", "content": prompt},
            ],
            temperature=0
        )
        # Extraire la réponse
        content = response.choices[0].message.content.strip()
        return content
    except Exception as e:
        st.error(f"Erreur lors de la catégorisation du mot-clé '{keyword}' : {e}")
        return None

@st.cache_data
def convert_df_to_excel(df):
    """
    Convertit un DataFrame en fichier Excel pour le téléchargement.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    processed_data = output.getvalue()
    return processed_data

###############################################################################
# Application principale
###############################################################################

st.title("GSC Scorecard")

# Récupération des identifiants GSC depuis les secrets de Streamlit
client_secret = st.secrets["installed"]["client_secret"]
client_id = st.secrets["installed"]["client_id"]
redirect_uri = st.secrets["installed"]["redirect_uris"][0]

###############################################################################
# Initialisation de l'état de session pour les jetons OAuth
###############################################################################

if "gsc_token_input" not in st.session_state:
    st.session_state["gsc_token_input"] = ""
if "gsc_token_received" not in st.session_state:
    st.session_state["gsc_token_received"] = False
if "credentials_fetched" not in st.session_state:
    st.session_state["credentials_fetched"] = None
if "account" not in st.session_state:
    st.session_state["account"] = None
if "site_urls" not in st.session_state:
    st.session_state["site_urls"] = []

# Instructions pour la récupération du code OAuth
with st.sidebar:
    st.markdown(
        f"""
        ### Étapes pour vous connecter à la Google Search Console :

        1. [Connectez-vous à GSC](https://accounts.google.com/o/oauth2/auth?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&scope=https://www.googleapis.com/auth/webmasters.readonly&access_type=offline&prompt=consent)
        2. Copiez le code d'autorisation obtenu.
        3. Collez-le ci-dessous et appuyez sur Entrée.
        """
    )

    # Entrée manuelle du code d'autorisation OAuth
    auth_code_input = st.text_input("Entrez le code OAuth de Google", value="", key="auth_code")

    if auth_code_input:
        st.session_state["gsc_token_input"] = auth_code_input
        st.session_state["gsc_token_received"] = True
        st.success("Code d'autorisation reçu.")

###############################################################################
# Gestion de l'authentification et récupération des données GSC
###############################################################################

if st.session_state.gsc_token_received:
    if not st.session_state["credentials_fetched"]:
        try:
            # Configuration du flux OAuth
            flow = Flow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uris": [redirect_uri],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://accounts.google.com/o/oauth2/token",
                    }
                },
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
                redirect_uri=redirect_uri,
            )
            # Échange du code d'autorisation contre les jetons
            flow.fetch_token(code=st.session_state.gsc_token_input)
            st.session_state["credentials_fetched"] = flow.credentials

            # Construction du service Google Search Console
            service = discovery.build(
                serviceName="webmasters",
                version="v3",
                credentials=st.session_state["credentials_fetched"],
                cache_discovery=False,
            )

            # Création de l'objet de compte Search Console
            st.session_state["account"] = searchconsole.account.Account(service, st.session_state["credentials_fetched"])

            # Récupération de la liste des sites
            site_list = service.sites().list().execute()
            first_value = list(site_list.values())[0]
            st.session_state["site_urls"] = [dicts.get("siteUrl") for dicts in first_value if dicts.get("siteUrl")]

            st.sidebar.info("✔️ Identifiants GSC valides !")
            st.success("Autorisation réussie.")

        except Exception as e:
            st.error(f"Une erreur est survenue lors de la récupération des jetons : {str(e)}")
    else:
        pass

    # Vérification que les crédentiels sont disponibles
    if st.session_state["credentials_fetched"]:
        # Formulaire pour la récupération des données
        with st.form(key="gsc_data_form"):
            # Sélection de la propriété Web
            selected_site = st.selectbox("Sélectionnez la propriété Web", st.session_state["site_urls"])

            # Sélection multiple des dimensions
            dimensions = st.multiselect(
                "Dimensions",
                ["query", "page", "date", "country", "device", "searchAppearance"],
                default=["query"],
                help="Choisissez une ou plusieurs dimensions pour l'analyse.",
            )

            # Type de recherche
            search_type = st.selectbox(
                "Type de recherche",
                ("web", "news", "video", "googleNews", "image"),
                help="Spécifiez le type de recherche.",
            )

            # Période de temps
            timescale = st.selectbox(
                "Plage de dates",
                ("Derniers 7 jours", "Derniers 30 jours", "Derniers 3 mois", "Derniers 6 mois", "Derniers 12 mois"),
                index=1,
                help="Spécifiez la plage de dates.",
            )

            # Mapping de la période de temps en jours
            timescale_mapping = {
                "Derniers 7 jours": -7,
                "Derniers 30 jours": -30,
                "Derniers 3 mois": -91,
                "Derniers 6 mois": -182,
                "Derniers 12 mois": -365,
            }

            selected_days = timescale_mapping.get(timescale, -30)

            # Sélection des métriques
            metric_options = ["clicks", "impressions", "ctr", "position"]
            selected_metrics = st.multiselect(
                "Sélectionnez les métriques",
                options=metric_options,
                default=["clicks"],
                help="Choisissez une ou plusieurs métriques pour l'analyse.",
            )

            # Bouton pour soumettre et récupérer les données GSC
            submit_gsc_data = st.form_submit_button(label="Fetch GSC Data")

            if submit_gsc_data:
                try:
                    # Accès à la propriété Web sélectionnée
                    webproperty = st.session_state["account"][selected_site]

                    # Récupération des données GSC
                    df = get_search_console_data(
                        webproperty,
                        search_type,
                        selected_days,
                        dimensions,
                    )

                    # Afficher les colonnes disponibles pour le débogage
                    st.write("Colonnes disponibles dans le DataFrame :", df.columns.tolist())

                    # Vérification si les données sont disponibles
                    if df.empty:
                        st.warning("🚨 Aucune donnée disponible. Veuillez affiner vos critères de recherche.")
                    else:
                        st.success(f"✅ Données récupérées avec succès ! Nombre total de lignes : {len(df)}")

                        # Vérification des dimensions sélectionnées
                        dimensions_absentes = [dim for dim in dimensions if dim not in df.columns]
                        if dimensions_absentes:
                            st.warning(f"🚨 Les dimensions suivantes ne sont pas présentes : {', '.join(dimensions_absentes)}")
                        else:
                            # Extraction des données principales
                            top_items_df = df.groupby(dimensions)[selected_metrics].sum().reset_index()

                            # Trier par la première métrique sélectionnée
                            if selected_metrics:
                                top_items_df = top_items_df.sort_values(by=selected_metrics[0], ascending=False).head(TOP_N_RESULTS)
                                st.write(f"### Top {TOP_N_RESULTS} éléments basés sur {selected_metrics[0].capitalize()}")
                                st.dataframe(top_items_df)
                            else:
                                st.warning("🚨 Aucune métrique sélectionnée.")
                except Exception as e:
                    st.error(f"Une erreur est survenue lors de la récupération des données : {str(e)}")
else:
    st.warning("Veuillez compléter le processus d'autorisation pour continuer.")
