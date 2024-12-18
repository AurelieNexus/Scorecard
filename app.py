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
TOP_N_KEYWORDS = 50  # Nombre de mots-clés à afficher

###############################################################################
# Fonctions auxiliaires
###############################################################################

def get_search_console_data(webproperty, search_type, selected_days, dimension, nested_dimension, nested_dimension_2):
    """
    Récupère les données de la Google Search Console en fonction des paramètres spécifiés.
    """
    q = webproperty.query.search_type(search_type).range("today", days=selected_days).dimension(dimension)

    if nested_dimension != "none":
        q = q.dimension(nested_dimension)
    if nested_dimension_2 != "none":
        q = q.dimension(nested_dimension_2)

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
        # Crédentiels déjà obtenus, aucune action nécessaire
        pass

    # Vérification que les crédentiels sont disponibles
    if st.session_state["credentials_fetched"]:
        # Formulaire pour la récupération des données
        with st.form(key="gsc_data_form"):
            # Sélection de la propriété Web
            selected_site = st.selectbox("Sélectionnez la propriété Web", st.session_state["site_urls"])

            # Définition des dimensions
            col1, col2, col3 = st.columns(3)

            with col1:
                dimension = st.selectbox(
                    "Dimension principale",
                    ("query", "page", "date", "country", "device", "searchAppearance"),
                    help="Dimension principale pour la requête.",
                )
            with col2:
                nested_dimension = st.selectbox(
                    "Dimension imbriquée",
                    ("none", "page", "date", "device", "searchAppearance", "country"),
                    help="Choisissez une dimension imbriquée.",
                )
            with col3:
                nested_dimension_2 = st.selectbox(
                    "Seconde dimension imbriquée",
                    ("none", "page", "date", "device", "searchAppearance", "country"),
                    help="Choisissez une seconde dimension imbriquée.",
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
                        dimension,
                        nested_dimension,
                        nested_dimension_2,
                    )

                    # Vérification si les données sont disponibles
                    if df.empty:
                        st.warning("🚨 Aucune donnée disponible. Veuillez affiner vos critères de recherche.")
                    else:
                        st.success(f"✅ Données récupérées avec succès ! Nombre total de lignes : {len(df)}")

                        # Sélection de la métrique pour les mots-clés principaux
                        metric = st.selectbox(
                            "Sélectionnez la métrique pour les mots-clés principaux",
                            options=["clicks", "impressions", "ctr", "position"],
                            help="Métrique pour la sélection des mots-clés principaux.",
                        )

                        # Extraction des mots-clés principaux
                        if 'query' in df.columns:
                            top_keywords_df = (
                                df.groupby('query')[metric]
                                .sum()
                                .reset_index()
                                .sort_values(by=metric, ascending=False)
                                .head(TOP_N_KEYWORDS)
                            )
                            top_keywords = top_keywords_df['query'].tolist()
                            st.write(f"### Top {TOP_N_KEYWORDS} mots-clés basés sur {metric.capitalize()}")
                            st.dataframe(top_keywords_df)
                        else:
                            st.warning("🚨 La dimension 'query' n'est pas présente dans les données.")
                except Exception as e:
                    st.error(f"Une erreur est survenue lors de la récupération des données : {str(e)}")
else:
    st.warning("Veuillez compléter le processus d'autorisation pour continuer.")
