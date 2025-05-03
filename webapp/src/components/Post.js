import { Badge, Card, Col, ListGroup, CloseButton, Button, ProgressBar } from "react-bootstrap";
import React, { useEffect, useState } from 'react';
import { getToken } from "../App" // Assure-toi que App.js exporte getToken
import axios from 'axios';

// Assure-toi que axios est configuré avec la bonne baseURL si nécessaire
// axios.defaults.baseURL = 'http://tf-lb-tes...com'; // ou http://localhost:8080 pour test local

function Post({ post, removePost, updatePost }) {
    const [showCard, setShowCard] = useState(true);
    const [attachment, setAttachment] = useState(null);
    // const [image, setImage] = useState(null); // image n'est plus un état local, vient des props
    const [labeling, setLabeling] = useState(false); // Initialisé à false
    const [uploading, setUploading] = useState(false); // Ajout pour gérer l'état d'upload

    const fileChanged = (e) => {
        const files = e.target.files || e.dataTransfer.files;
        if (!files.length) return;
        console.log("File selected:", files[0]);
        setAttachment(files[0]);
    }

    const getSignedUrlPut = async (postIdForUrl) => { // Renommé pour éviter conflit
        console.log("Getting signed URL for postId:", postIdForUrl);
        if (!attachment) {
             console.error("No attachment selected for getSignedUrlPut");
             return null;
        }
        console.log("Attachment details:", attachment.name, attachment.type);
        const config = {
            headers: { Authorization: getToken() },
            params: {
                filename: attachment.name,
                filetype: attachment.type,
                postId: postIdForUrl, // Utiliser l'ID SANS préfixe ici, comme attendu par getSignedUrl
            },
        };

        try {
            // ATTENTION: Assure-toi que axios utilise la bonne baseURL (LB ou localhost)
            const response = await axios.get("/signedUrlPut", config);
            console.log("Signed URL response:", response.data);
            if (response.data && response.data.uploadURL) {
               return response.data; // Retourne tout l'objet {uploadURL, objectName}
            } else {
                console.error("Invalid response from /signedUrlPut:", response.data);
                return null;
            }
        } catch (error) {
            console.error("Error getting signed URL:", error);
            alert("Error getting upload URL. Check console.");
            return null;
        }
    }

    const submitFile = async () => {
        if (!attachment) {
            alert("Please select a file to upload.");
            return;
        }
        // On suppose que post.id VIENT de l'API avec le préfixe POST#
        // getSignedUrl attend l'ID SANS préfixe
        const postIdWithoutPrefix = post.id.includes("#") ? post.id.split("#")[1] : post.id;
        if (!postIdWithoutPrefix) {
            console.error("Could not extract post ID without prefix from:", post.id);
            alert("Error processing post ID.");
            return;
        }

        setUploading(true); // Indique le début de l'upload

        const signedUrlData = await getSignedUrlPut(postIdWithoutPrefix);

        if (!signedUrlData || !signedUrlData.uploadURL) {
            setUploading(false); // Arrête l'indicateur d'upload en cas d'erreur
            return; // Erreur déjà gérée dans getSignedUrlPut
        }

        const uploadUrl = signedUrlData.uploadURL;

        const config = {
            headers: { "Content-Type": attachment.type },
        };
        console.log(`Uploading to S3: ${uploadUrl}`);

        var instance = axios.create();
        // IMPORTANT: Pas besoin de supprimer l'Authorization pour les URL pré-signées PUT S3 standard
        // delete instance.defaults.headers.common['Authorization'];

        try {
            const res = await instance.put(uploadUrl, attachment, config);
            console.log("S3 Upload Status:", res.status); // HTTP status (devrait être 200)

            if (res.status === 200) {
                // L'upload S3 a réussi, on peut déclencher la mise à jour et le spinner de labellisation
                setLabeling(true); // Démarre l'indicateur de labellisation
                // Attendre un peu pour que la Lambda ait une chance de s'exécuter
                // Idéalement, il faudrait un mécanisme de notification (ex: WebSocket)
                // ou un rafraîchissement périodique plus intelligent.
                setTimeout(() => {
                    setLabeling(false); // Arrête l'indicateur
                    updatePost(); // Rafraîchit les données du post (qui devraient maintenant avoir image/labels)
                }, 5000); // Augmenté à 5 secondes pour laisser le temps à la Lambda
            } else {
                 alert(`Upload failed with status: ${res.status}`);
                 setLabeling(false);
            }
        } catch (error) {
            console.error("Error uploading file to S3:", error);
            alert("Error uploading file. Check console.");
            setLabeling(false); // Assure-toi d'arrêter l'indicateur en cas d'erreur
        } finally {
             setUploading(false); // Arrête l'indicateur d'upload
        }
    }

    const deletePost = async () => {
        // On suppose que post.id VIENT de l'API avec le préfixe POST#
        const idWithoutPrefix = post.id.includes("#") ? post.id.split("#")[1] : post.id;
         if (!idWithoutPrefix) {
            console.error("Could not extract post ID without prefix from:", post.id);
            alert("Error processing post ID for deletion.");
            return;
        }
        console.log(`Attempting to delete post with ID (no prefix): ${idWithoutPrefix}`);
        try {
            // ATTENTION: Assure-toi que axios utilise la bonne baseURL (LB ou localhost)
            const res = await axios.delete(`/posts/${idWithoutPrefix}`, { headers: { Authorization: getToken() } });
            console.log("Delete successful:", res.data);
            setShowCard(false); // Masque la carte après suppression réussie
            // removePost(post.id); // Appelle la fonction du parent si nécessaire pour MAJ la liste globale
        } catch (error) {
            console.error('Error deleting post:', error.response ? error.response.data : error.message);
            alert(`Error deleting post: ${error.response ? error.response.data.message : error.message}`);
        }
    };

    // Détermine si l'image existe déjà (basé sur la clé S3 stockée)
    // Note: On utilise image_s3_key car c'est ce qui est stocké dans DynamoDB par la lambda
    const imageExists = !!post.image_s3_key;

    return (<>
        {showCard && (
            <Col>
                {/* Clé ajoutée ici, même si le parent devrait aussi en avoir une */}
                <Card style={{ marginTop: '1rem' }} key={post.id}>
                    <Card.Header >
                        {post.title}
                        <CloseButton className="float-end" onClick={deletePost} aria-label="Delete Post"/>
                    </Card.Header>

                    {/* CORRECTION : Utilise post.image_url et vérifie son existence */}
                    {post.image_url && (
                        <Card.Img variant="top" src={post.image_url} alt={post.title} />
                    )}

                    <Card.Body>
                        <Card.Text>
                            {post.body}
                        </Card.Text>
                    </Card.Body>

                    <ListGroup variant="flush">
                        {/* Affiche les labels SI l'image existe ET qu'il y a des labels */}
                        {(imageExists && post.labels && post.labels.length > 0) && (
                             <ListGroup.Item>
                                {post.labels.map((label) => (
                                    // CORRECTION : Ajout de key={label}
                                    <Badge key={label} bg="info" style={{ marginRight: '0.25rem' }}>
                                        {label}
                                    </Badge>
                                ))}
                            </ListGroup.Item>
                        )}

                        {/* Affiche le formulaire d'upload SI l'image N'EXISTE PAS ENCORE */}
                        {!imageExists && (
                            <ListGroup.Item>
                                Attachment:
                                <input type="file" onChange={fileChanged} disabled={uploading || labeling} style={{ margin: '0 0.5rem' }} />
                                <Button
                                    variant="primary"
                                    onClick={submitFile}
                                    disabled={!attachment || uploading || labeling}
                                >
                                    {uploading ? "Uploading..." : "Upload"}
                                </Button>
                                {labeling && <ProgressLabeling/>}
                            </ListGroup.Item>
                        )}

                         {/* Affiche 'Labeling...' si l'image existe mais pas encore les labels */}
                         {(imageExists && (!post.labels || post.labels.length === 0)) && (
                            <ListGroup.Item>
                                Detecting labels... <ProgressBar animated now={100} />
                            </ListGroup.Item>
                         )}

                    </ListGroup>
                </Card>
            </Col>
        )}
    </>
    )
}


function ProgressLabeling() {
    const [progress, setProgress] = useState(0);
  
    useEffect(() => {
      const timer = setInterval(() => {
        if (progress < 100) {
          setProgress(progress + 1);
        }
      }, 10);
  
      return () => {
        clearInterval(timer);
      };
    }, [progress]);
  
    return (
      <div className="App">
        <ProgressBar now={progress} label="Detecting labels" />
      </div>
    );
  }
  


export default Post