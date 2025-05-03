import { Badge, Card, Col, ListGroup, CloseButton, Button, ProgressBar } from "react-bootstrap";
import React, { useEffect, useState } from 'react';
import { getToken } from "../App";
import axios from 'axios';


function Post({ post, removePost, updatePost }) {
    const [showCard, setShowCard] = useState(true);
    const [attachment, setAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isLabeling, setIsLabeling] = useState(false);

    const handleFileChange = (e) => {
        const files = e.target.files || e.dataTransfer.files;
        if (files && files.length > 0) {
            console.log("File selected:", files[0]);
            setAttachment(files[0]);
        } else {
            setAttachment(null);
        }
    };

    const getSignedUrlForUpload = async () => {
        if (!attachment) {
            console.error("No attachment selected.");
            return null;
        }
        const postId = post.id;
        if (!postId) {
            console.error("Post ID is missing.");
            return null;
        }

        console.log(`Getting signed URL for postId: ${postId}, filename: ${attachment.name}`);
        const config = {
            headers: { Authorization: getToken() },
            params: {
                filename: attachment.name,
                filetype: attachment.type,
                postId: postId,
            },
        };

        try {
            const response = await axios.get("/signedUrlPut", config);
            console.log("Signed URL response:", response.data);
            if (response.data && response.data.uploadURL) {
                return response.data;
            } else {
                console.error("Invalid response from /signedUrlPut:", response.data);
                alert("Error: Could not get upload URL from server.");
                return null;
            }
        } catch (error) {
            console.error("Error getting signed URL:", error.response ? error.response.data : error.message);
            alert(`Error getting upload URL: ${error.response ? error.response.data.message : error.message}. Check console.`);
            return null;
        }
    };

    const uploadFileToS3 = async (uploadUrl) => {
        if (!attachment) return false;

        const config = {
            headers: { "Content-Type": attachment.type },
        };
        console.log(`Uploading ${attachment.name} to S3...`);

        const s3AxiosInstance = axios.create();
        try {
            const res = await s3AxiosInstance.put(uploadUrl, attachment, config);
            console.log("S3 Upload Status:", res.status);
            return res.status === 200;
        } catch (error) {
            console.error("Error uploading file to S3:", error);
            alert("Error uploading file to storage. Check console.");
            return false;
        }
    };

    const handleSubmitFile = async () => {
        setIsUploading(true);
        setIsLabeling(false);

        const signedUrlData = await getSignedUrlForUpload();
        if (!signedUrlData) {
            setIsUploading(false);
            return;
        }

        const uploadSuccess = await uploadFileToS3(signedUrlData.uploadURL);

        setIsUploading(false);

        if (uploadSuccess) {
            console.log("Upload successful. Waiting for labeling...");
            setIsLabeling(true);
            setTimeout(() => {
                setIsLabeling(false);
                updatePost();
            }, 5000); 
        }
    };

    const handleDeletePost = async () => {
        // post.id est maintenant SANS préfixe
        const idToDelete = post.id;
        if (!idToDelete) {
            console.error("Cannot delete post: ID is missing.");
            alert("Error: Cannot delete post due to missing ID.");
            return;
        }

        const confirmDelete = window.confirm(`Are you sure you want to delete post "${post.title}"?`);
        if (!confirmDelete) {
            return;
        }

        console.log(`Attempting to delete post with ID: ${idToDelete}`);
        try {
            const res = await axios.delete(`/posts/${idToDelete}`, { headers: { Authorization: getToken() } });
            console.log("Delete successful:", res.data);
            setShowCard(false);
            if (removePost) {
                removePost(post.id);
            }
        } catch (error) {
            console.error('Error deleting post:', error.response ? error.response.data : error.message);
            alert(`Error deleting post: ${error.response ? error.response.data.message : error.message}`);
        }
    };

    const hasImageAssociated = !!post.image_s3_key; 
    const hasImageUrl = !!post.image_url;  
    const hasLabels = post.labels && post.labels.length > 0;

    return (
        <>
            {showCard && (
                <Col>
                    <Card style={{ marginTop: '1rem' }} key={post.id}>
                        <Card.Header>
                            {post.title}
                            <CloseButton
                                className="float-end"
                                onClick={handleDeletePost}
                                aria-label="Delete Post"
                            />
                        </Card.Header>

                        {hasImageUrl && (
                            <Card.Img variant="top" src={post.image_url} alt={post.title} />
                        )}
                        {!hasImageUrl && hasImageAssociated && (
                            <div style={{textAlign: 'center', padding: '1rem', background: '#eee'}}>Image processing or URL error...</div>
                        )}

                        <Card.Body>
                            <Card.Text>
                                {post.body}
                            </Card.Text>
                        </Card.Body>

                        <ListGroup variant="flush">
                            {hasLabels && (
                                <ListGroup.Item>
                                    {post.labels.map((label) => (
                                        <Badge key={label} bg="info" style={{ marginRight: '0.25rem' }}>
                                            {label}
                                        </Badge>
                                    ))}
                                </ListGroup.Item>
                            )}

                            {!hasImageAssociated && (
                                <ListGroup.Item>
                                    Attach Image:
                                    <input
                                        type="file"
                                        onChange={handleFileChange}
                                        disabled={isUploading || isLabeling}
                                        style={{ margin: '0 0.5rem' }}
                                    />
                                    <Button
                                        variant="primary"
                                        onClick={handleSubmitFile}
                                        disabled={!attachment || isUploading || isLabeling}
                                    >
                                        {isUploading ? "Uploading..." : "Upload"}
                                    </Button>
                                </ListGroup.Item>
                            )}

                            
                            {isLabeling && (
                                 <ListGroup.Item>
                                    <ProgressLabeling />
                                 </ListGroup.Item>
                            )}


                        </ListGroup>
                    </Card>
                </Col>
            )}
        </>
    );
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


export default Post;